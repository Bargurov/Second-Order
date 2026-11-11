// Screenshots of the metals page for a visual review (metals-check.mjs, SECOND_ORDER_SCREENSHOTS=<folder>): each a
// viewport, never a tall page; desktop 1280x900 and phone 390x844.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export async function takeShots(shots, { send, load, evaluate, sleep }) {
  mkdirSync(shots, { recursive: true });
  const shot = async (name, width, height, mobile, path, action) => {
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
    await load(path);
    if (action) await evaluate(action);
    await sleep(600);
    const image = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(image.data, "base64"));
  };
  const openPanel = `document.querySelector(".mt-picker-button").click(); true`;
  const toTabs = `document.querySelector(".mt-tabs").scrollIntoView({ block: "start" }); true`;
  const showFold = (part) => `(() => { const d = document.querySelector('#mt-metal-panel details[data-part="${part}"]'); d.open = true;
    d.scrollIntoView({ block: "start" }); return true; })()`;
  await shot("desktop-1-first-screen", 1280, 900, false, "/metals");
  await shot("desktop-2-picker-open", 1280, 900, false, "/metals", openPanel);
  await shot("desktop-3-overview-concentration", 1280, 900, false, "/metals",
    `document.querySelector('[data-switch] button[data-mode="concentration"]').click(); ${toTabs}`);
  await shot("desktop-4-copper-snapshot", 1280, 900, false, "/metals#by-metal:copper", toTabs);
  await shot("desktop-5-copper-concentration", 1280, 900, false, "/metals#by-metal:copper", showFold("concentration"));
  await shot("desktop-6-copper-transmission", 1280, 900, false, "/metals#by-metal:copper", showFold("transmission"));
  await shot("desktop-7-method", 1280, 900, false, "/metals#method", toTabs);
  // Two 2025 reliance figures under one detail, each named by its commodity; events named by their source.
  await shot("desktop-8-bauxite-snapshot", 1280, 900, false, "/metals?m=bauxite-and-alumina#by-metal:bauxite-and-alumina",
    toTabs);
  await shot("desktop-9-copper-exposure", 1280, 900, false, "/metals#by-metal:copper", showFold("exposure"));
  await shot("desktop-10-copper-uses", 1280, 900, false, "/metals#by-metal:copper", showFold("uses"));
  await shot("phone-1-first-screen", 390, 844, true, "/metals");
  await shot("phone-2-picker-open", 390, 844, true, "/metals", openPanel);
  await shot("phone-3-copper-snapshot", 390, 844, true, "/metals#by-metal:copper", toTabs);
  await shot("phone-4-copper-transmission", 390, 844, true, "/metals#by-metal:copper", showFold("transmission"));
  await shot("phone-5-copper-exposure", 390, 844, true, "/metals#by-metal:copper", showFold("exposure"));
}
