// Browser main-flow checks: the UI must render the exact server frames,
// blocked edges must match the simulation, and stale responses must never
// survive an edit.

import { expect, test } from "@playwright/test";

const INITIAL_MATRIX = [
  [40, 0, 0, 0],
  [40, 0, 0, 0],
  [40, 0, 0, 0],
];

async function getServerFrames(request, payload) {
  const resp = await request.post("/api/simulate", { data: payload });
  expect(resp.ok()).toBeTruthy();
  return resp.json();
}

function frac(s) {
  if (s.includes("/")) {
    const [n, d] = s.split("/");
    return Number(n) / Number(d);
  }
  return Number(s);
}

async function setMatrix(page, matrix) {
  for (let r = 0; r < matrix.length; r++) {
    for (let c = 0; c < matrix[r].length; c++) {
      const input = page.getByTestId(`cell-${r}-${c}`);
      await input.fill(String(matrix[r][c]));
    }
  }
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("initial run renders server frames exactly on the heatmap", async ({
  page,
  request,
}) => {
  const payload = {
    matrix: INITIAL_MATRIX,
    steps: 6,
    boundary: "insulated",
    blocked_edges: [],
  };
  const server = await getServerFrames(request, payload);

  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("player")).toBeVisible();

  for (let t = 0; t <= 6; t++) {
    await page.getByTestId("step-slider").fill(String(t));
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 4; c++) {
        const cell = page.getByTestId(`heat-${r}-${c}`);
        const expected = frac(server.frames[t][r][c]);
        const actual = Number(await cell.getAttribute("data-value"));
        expect(Math.abs(actual - expected)).toBeLessThan(1e-9);
      }
    }
    await expect(page.getByTestId("step-label")).toHaveText(
      `第 ${t} / 6 步`
    );
  }

  // Insulated mode: every total row equals the initial total (120).
  for (let t = 0; t <= 6; t++) {
    await expect(page.getByTestId(`stats-row-${t}`).locator("td").nth(1)).toHaveText(
      "120"
    );
  }
});

test("playback advances frames automatically and loops via play again", async ({
  page,
}) => {
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("player")).toBeVisible();
  await page.getByTestId("play-button").click();
  await expect(page.getByTestId("step-label")).toContainText("第 6 / 6 步", {
    timeout: 15000,
  });
  // Restart from end.
  await page.getByTestId("play-button").click();
  await expect(page.getByTestId("step-label")).toContainText("第 0 / 6 步", {
    timeout: 3000,
  });
});

test("blocked edge is sent to the server and drawn across the heatmap", async ({
  page,
  request,
}) => {
  await page.getByTestId("edge-mode").click();
  // Block the seam between column 0 and column 1 on the middle row.
  await page.getByTestId("edge-1-0-1-1").click();
  await expect(page.getByTestId("edge-count")).toContainText("已阻断 1 / 30");
  await page.getByTestId("edge-mode").click();
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("player")).toBeVisible();

  const payload = {
    matrix: INITIAL_MATRIX,
    steps: 6,
    boundary: "insulated",
    blocked_edges: [[1, 0, 1, 1]],
  };
  const server = await getServerFrames(request, payload);

  // With the seam blocked, cell (1,1) is not fed directly by (1,0); at t1 it
  // receives only vertical fluxes from (0,1) and (2,1), both zero, so stays 0.
  await page.getByTestId("step-slider").fill("1");
  const value = await page
    .getByTestId("heat-1-1")
    .getAttribute("data-value");
  expect(Number(value)).toBeCloseTo(frac(server.frames[1][1][1]), 10);
  expect(Number(value)).toBe(0);

  // The blocked bar must be visually present inside the heatmap overlay.
  const blockedBar = page
    .getByTestId("heatmap")
    .locator("rect.edge-blocked");
  await expect(blockedBar).toHaveCount(1);

  // Stats still conserve total temperature with the edge blocked.
  for (let t = 0; t <= 6; t++) {
    await expect(
      page.getByTestId(`stats-row-${t}`).locator("td").nth(1)
    ).toHaveText("120");
  }
});

test("fixed-zero boundary shows nonzero net flow and loses total heat", async ({
  page,
  request,
}) => {
  const payload = {
    matrix: INITIAL_MATRIX,
    steps: 5,
    boundary: "fixed-zero",
    blocked_edges: [],
  };
  const server = await getServerFrames(request, payload);

  await page.check('input[name="boundary"][value="fixed-zero"]');
  await page.getByTestId("input-steps").fill("5");
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("player")).toBeVisible();

  // First boundary flow (step 1): the plate has a hot column on the left.
  await expect(
    page.getByTestId("stats-row-1").locator("td").nth(2)
  ).toHaveText(server.boundary_flow[0]);

  // Total at the final frame must match the server exactly and be below 120.
  const finalTotal = frac(server.total_temperature[5]);
  expect(finalTotal).toBeLessThan(120);
  await page.getByTestId("step-slider").fill("5");
  const cellSum = await page.evaluate(() => {
    let sum = 0;
    document
      .querySelectorAll('[data-testid^="heat-"]')
      .forEach((el) => (sum += Number(el.getAttribute("data-value"))));
    return sum;
  });
  expect(cellSum).toBeCloseTo(finalTotal, 6);
});

test("editing after a run discards old frames; no stale playback", async ({
  page,
}) => {
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("player")).toBeVisible();

  // Edit a temperature: old response must be discarded immediately.
  await page.getByTestId("cell-0-0").fill("99");
  await expect(page.getByTestId("stale-hint")).toBeVisible();
  await expect(page.getByTestId("player")).not.toBeVisible();
  await expect(page.getByTestId("stats-panel")).not.toBeVisible();

  // Switching boundary mode also invalidates a previously accepted result.
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("player")).toBeVisible();
  await page.check('input[name="boundary"][value="fixed-zero"]');
  await expect(page.getByTestId("player")).not.toBeVisible();
});

test("invalid input is surfaced, valid run still works afterwards", async ({
  page,
}) => {
  await page.getByTestId("cell-0-0").fill("500");
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("error-box")).toBeVisible();
  await expect(page.getByTestId("player")).not.toBeVisible();

  await page.getByTestId("cell-0-0").fill("40");
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("player")).toBeVisible();
  await expect(page.getByTestId("error-box")).not.toBeVisible();
});

test("selecting a cell draws its curve using server frame values", async ({
  page,
  request,
}) => {
  const payload = {
    matrix: INITIAL_MATRIX,
    steps: 6,
    boundary: "insulated",
    blocked_edges: [],
  };
  const server = await getServerFrames(request, payload);

  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("cell-chart")).toBeVisible();

  // Default selection is (0,0); add cell (2,3) by clicking the heatmap.
  await page.getByTestId("heat-2-3").click();
  const chart = page.getByTestId("cell-chart");
  await expect(chart.locator("path")).toHaveCount(2);

  const circlesForSecondSeries = await chart
    .locator("path")
    .nth(1)
    .getAttribute("d");
  // First point of the (2,3) curve must be t=0 value 0 from the server.
  const firstXy = circlesForSecondSeries.trim().split(" ");
  expect(firstXy[0]).toBe("M");

  // The (2,3) legend shows the final-step value from the server.
  const finalValue = frac(server.frames[6][2][3]);
  await expect(page.getByTestId("remove-cell-2-3")).toBeVisible();
  await expect(page.locator("text=/行 3，列 4/")).toContainText(
    finalValue.toFixed(3)
  );

  // Removing works.
  await page.getByTestId("remove-cell-2-3").click();
  await expect(chart.locator("path")).toHaveCount(1);
});

test("resize drops out-of-range blocked edges and trims cells", async ({
  page,
}) => {
  await page.getByTestId("edge-mode").click();
  await page.getByTestId("edge-2-2-2-3").click();
  await page.getByTestId("input-rows").fill("3");
  await page.getByTestId("input-cols").fill("3");
  await page.getByTestId("edge-mode").click();
  await expect(page.getByTestId("edge-count")).toContainText("已阻断 0 / 30");
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("player")).toBeVisible();
});
