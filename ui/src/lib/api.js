// API client for the plate simulation service.

export async function simulate(payload, signal) {
  let resp;
  try {
    resp = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new Error("无法连接模拟服务，请确认 plate-api 已启动");
  }
  if (!resp.ok) {
    let message = `服务返回 ${resp.status}`;
    try {
      const data = await resp.json();
      if (data && data.error) message = data.error;
    } catch {
      // keep default message
    }
    throw new Error(message);
  }
  return resp.json();
}

export async function getConstraints(signal) {
  const resp = await fetch("/api/constraints", { signal });
  if (!resp.ok) throw new Error("无法获取输入约束");
  return resp.json();
}
