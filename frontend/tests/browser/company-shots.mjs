// Screenshots of the FCX company page for a visual review (company-check.mjs, SECOND_ORDER_SCREENSHOTS=<folder>): each a
// viewport, never a tall page; desktop 1280x900 and phone 390x844 (headless-chrome-tall-screenshots: tall captures hang).
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export async function takeShots(shots, { send, load, evaluate, sleep }, prefix = "") {
  mkdirSync(shots, { recursive: true });
  const shot = async (name, width, height, mobile, path, action, wait) => {
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
    await load(path, wait);
    if (action) await evaluate(action);
    await sleep(500);
    const image = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${prefix}${name}.png`), Buffer.from(image.data, "base64"));
  };
  const scrollTo = (selector) => `(() => { document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: "start" }); return true; })()`;
  const openDetail = `(() => { document.querySelector('.co-tile .co-fig')?.click(); return true; })()`;
  const openChange = `(() => { const b = document.querySelector('.co-change[data-change="revenue"] .co-more'); b?.click();
    b?.closest(".co-change")?.scrollIntoView({ block: "start" }); return true; })()`;
  const openFold = (part) => `(() => { const d = document.querySelector('details[data-part="${part}"]'); if (d) { d.open = true;
    d.scrollIntoView({ block: "start" }); } return true; })()`;
  if (prefix) {  // a withheld state: the first screen and the part that shows what is not shown
    await shot("desktop-1-first-screen", 1280, 900, false, "/companies/fcx");
    await shot("desktop-2-mechanisms-bagdad", 1280, 900, false, "/companies/fcx#mechanisms", scrollTo(".co-bagdad"));
    await shot("desktop-3-method", 1280, 900, false, "/companies/fcx#method");
    await shot("phone-1-first-screen", 390, 844, true, "/companies/fcx");
    return;
  }
  await shot("desktop-1-first-screen", 1280, 900, false, "/companies/fcx");
  await shot("desktop-2-figures-and-changes", 1280, 900, false, "/companies/fcx", scrollTo(".co-tiles"));
  await shot("desktop-3-change-opened", 1280, 900, false, "/companies/fcx", openChange);
  await shot("desktop-4-figure-detail", 1280, 900, false, "/companies/fcx", openDetail);
  await shot("desktop-5-business", 1280, 900, false, "/companies/fcx#business");
  await shot("desktop-6-numbers-quarter", 1280, 900, false, "/companies/fcx#numbers");
  await shot("desktop-7-numbers-bridge", 1280, 900, false, "/companies/fcx#numbers:nine-months",
    openFold("nine-months-The company's revenue bridge"));
  await shot("desktop-8-mechanisms", 1280, 900, false, "/companies/fcx#mechanisms");
  await shot("desktop-9-sensitivities", 1280, 900, false, "/companies/fcx#mechanisms", scrollTo(".co-sens"));
  await shot("desktop-10-bagdad", 1280, 900, false, "/companies/fcx#mechanisms", scrollTo(".co-bagdad"));
  await shot("desktop-11-questions", 1280, 900, false, "/companies/fcx#questions");
  await shot("desktop-12-method", 1280, 900, false, "/companies/fcx#method");
  await shot("phone-1-first-screen", 390, 844, true, "/companies/fcx");
  await shot("phone-2-figures", 390, 844, true, "/companies/fcx", scrollTo(".co-tiles"));
  await shot("phone-3-changes", 390, 844, true, "/companies/fcx", scrollTo(".co-changes"));
  await shot("phone-4-figure-detail", 390, 844, true, "/companies/fcx", openDetail);
  await shot("phone-5-numbers", 390, 844, true, "/companies/fcx#numbers");
  await shot("phone-6-bagdad", 390, 844, true, "/companies/fcx#mechanisms", scrollTo(".co-bagdad"));
  await shot("phone-7-method", 390, 844, true, "/companies/fcx#method");
  await shot("phone-8-fuller-summary", 390, 844, true, "/companies/fcx", openFold("summary-more"));
  const card = `!!document.querySelector('[data-company-card="fcx"]')`;
  const thesisLink = `!!document.querySelector('[data-tools="company"]')`;
  await shot("desktop-13-library-card", 1280, 900, false, "/library", scrollTo("#companies"), card);
  await shot("desktop-14-thesis-link", 1280, 900, false, "/theses/copper", scrollTo(".thesis-tools"), thesisLink);
  await shot("phone-9-library-card", 390, 844, true, "/library", scrollTo("#companies"), card);
}
