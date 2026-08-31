/* Thin server-side boundary around the official Prozorro EDS client. */
globalThis.window ??= globalThis;

const TIMEOUT_MS = Math.max(1000, Number(process.env.PQM_EDS_TIMEOUT_MS || 25000));

function cleanTime(value) {
  if (!value || typeof value !== "object") return null;
  const fields = ["year", "month", "day", "hour", "minute", "second", "milliseconds"];
  const result = {};
  for (const field of fields) {
    const number = Number(value[field]);
    if (Number.isFinite(number)) result[field] = number;
  }
  return Object.keys(result).length ? result : null;
}

function cleanSigner(value) {
  const signer = value && typeof value === "object" ? value : {};
  const text = field => typeof signer[field] === "string" ? signer[field] : "";
  return {
    subjectCN: text("subjectCN"),
    subjectOrg: text("subjectOrg"),
    subjectEDRPOUCode: text("subjectEDRPOUCode"),
    subjectDRFOCode: text("subjectDRFOCode"),
    subjectTitle: text("subjectTitle"),
    issuerCN: text("issuerCN"),
    serial: text("serial"),
    isFilled: signer.isFilled === true,
    isTimeAvail: signer.isTimeAvail === true,
    isTimeStamp: signer.isTimeStamp === true,
    time: cleanTime(signer.time),
  };
}

function classify(error) {
  const message = String(error?.message || error || "Невідома технічна помилка");
  const status = Number(error?.response?.status || 0);
  const code = String(error?.code || "");
  if (status >= 500 || ["ECONNABORTED", "ECONNREFUSED", "ENOTFOUND", "ETIMEDOUT"].includes(code)) {
    return { status: "service_unavailable", error: "Сервіс перевірки підпису тимчасово недоступний" };
  }
  if ((status >= 400 && status < 500) || /invalid|format|підпис|signature|verify|01[6789]/i.test(message)) {
    return { status: "unsupported_or_invalid", error: "Формат підпису не підтримується або файл підпису некоректний" };
  }
  return { status: "technical_error", error: "Не вдалося виконати автоматичну перевірку підпису" };
}

async function main() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const payload = JSON.parse(input || "{}");
  if (!/^https?:\/\//i.test(String(payload.signUrl || ""))) {
    process.stdout.write(JSON.stringify({ status: "unsupported_or_invalid", error: "Некоректне посилання на файл підпису" }));
    return;
  }
  try {
    const { ProzorroEds } = await import("@prozorro/prozorro-eds");
    await ProzorroEds.init({ debug: false, environment: "production" });
    const response = await Promise.race([
      ProzorroEds.verify({ signUrl: payload.signUrl }),
      new Promise((_, reject) => setTimeout(() => {
        const error = new Error("EDS verification timeout");
        error.code = "ETIMEDOUT";
        reject(error);
      }, TIMEOUT_MS)),
    ]);
    const signers = Array.isArray(response?.signers) ? response.signers.map(cleanSigner) : [];
    if (!signers.length) {
      process.stdout.write(JSON.stringify({ status: "unsupported_or_invalid", error: "У підписі не знайдено даних підписанта", signers: [] }));
      return;
    }
    process.stdout.write(JSON.stringify({ status: "success", signer_count: signers.length, signers }));
  } catch (error) {
    process.stdout.write(JSON.stringify(classify(error)));
  }
}

main().catch(() => {
  process.stdout.write(JSON.stringify({ status: "technical_error", error: "Не вдалося запустити перевірку підпису" }));
});
