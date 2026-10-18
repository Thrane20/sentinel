import { expect, test } from "@playwright/test";
test("iPhone camera discovery, filters, and no horizontal overflow", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByText("Stream bridge needs setup", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Live cameras" }),
  ).toBeVisible();
  await expect(page.locator(".camera-card")).toHaveCount(8);
  await expect(page.getByText("SNAPSHOT / 1S")).toHaveCount(0);
  await expect(page.locator(".connect-overlay")).toHaveCount(0);
  await expect(page.getByText("Open live stream")).toHaveCount(0);
  const header = page.locator(".topbar");
  const summary = page.locator(".live-summary");
  const headerBox = await header.boundingBox();
  const summaryBox = await summary.boundingBox();
  expect(
    headerBox && summaryBox && summaryBox.y >= headerBox.y + headerBox.height,
  ).toBe(true);
  await page.getByRole("button", { name: "Entry", exact: true }).click();
  await expect(page.locator(".camera-card")).toHaveCount(3);
  await page.getByRole("button", { name: "All cameras", exact: true }).click();
  await page
    .getByRole("button", { name: "Include previously offline cameras" })
    .click();
  await expect(page.locator(".camera-card")).toHaveCount(7);
  await page.getByRole("textbox", { name: "Search cameras" }).fill("pool");
  await expect(page.locator(".camera-card")).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("camera dialog reports missing credentials and restores focus", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByText("Stream bridge needs setup", { exact: true }),
  ).toBeVisible();
  const camera = page.locator(".camera-card").first();
  await camera.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByText(
      "Add recorder credentials to .env.local and restart Sentinel.",
    ),
  ).toBeVisible();
  await page.setViewportSize({ width: 844, height: 390 });
  const landscapeBox = await page.getByRole("dialog").boundingBox();
  expect(landscapeBox?.width).toBeGreaterThanOrEqual(840);
  expect(landscapeBox?.height).toBeGreaterThanOrEqual(386);
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "Front Door" }),
  ).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Close camera" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "Front Door" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close camera" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(camera).toBeFocused();
});
test("playback lists and clears collected IVSEC alerts", async ({ page }) => {
  let cleared = false;
  await page.route("**/api/playback/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "video/mp4",
      body: Buffer.from([]),
    }),
  );
  await page.route("**/api/ivsec/events", async (route) => {
    if (route.request().method() === "DELETE") {
      cleared = true;
      return route.fulfill({ json: { cleared: 1 } });
    }
    return route.fulfill({
      json: {
        events: cleared
          ? []
          : [
              {
                id: 1,
                cameraId: "05",
                cameraName: "Front Drive",
                eventType: "Motion",
                sourceTime: "09/07/2026 17:05:30",
                capturedAt: 1788764730,
              },
            ],
        health: {
          online: true,
          configured: true,
          lastPoll: 1788764730,
          error: null,
        },
      },
    });
  });
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await expect(
    page.getByText("Stream bridge needs setup", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("button", { name: "Playback" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Footage review" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "IVSEC alerts" }),
  ).toBeVisible();
  await expect(page.getByText("Recorder feed connected")).toBeVisible();
  await expect(page.getByText("Motion", { exact: true })).toBeVisible();
  await expect(page.getByText("CH 05", { exact: true })).toBeVisible();
  await expect(page.getByText("Front Drive", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Motion/ }).click();
  const cameraDialog = page.locator(".camera-dialog");
  await expect(cameraDialog).toBeVisible();
  await expect(cameraDialog.getByLabel("Playback time")).toHaveValue(
    "2026-09-07T17:05:30",
  );
  await expect(cameraDialog.locator("video")).toHaveAttribute(
    "src",
    /\/api\/playback\/05\?at=1788764730/,
  );
  await cameraDialog.getByRole("button", { name: "Close camera" }).click();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No collected alerts" }),
  ).toBeVisible();
  await expect(page.getByText("Cleared 1 collected alerts.")).toBeVisible();

  await page
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("button", { name: "System" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Channel inventory" }),
  ).toBeVisible();
  await expect(page.locator(".inventory-row")).toHaveCount(8);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("animal detection has an iPhone-ready offline state", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Mobile navigation" })
    .getByRole("button", { name: "Animals" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Perimeter life signs." }),
  ).toBeVisible();
  await expect(
    page.getByText("Animal detection services are not available yet."),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "No animals logged" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("animal event cards and controls render from the local service", async ({
  page,
}) => {
  await page.route("**/api/playback/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "video/mp4",
      body: Buffer.from([]),
    }),
  );
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: {
        configured: true,
        host: "recorder.local",
        metadataSource: "test",
        animals: {
          online: true,
          mqttOnline: true,
          frigateOnline: true,
          model: "MDV6-mit-yolov9-c",
          provider: "GPU",
          inferenceSpeedMs: 14.2,
          alertsConfigured: true,
          alertsEnabled: false,
          enabledCameras: 6,
        },
      },
    }),
  );
  await page.route("**/api/animals/settings", (route) =>
    route.fulfill({
      json: {
        globalEnabled: true,
        alertsEnabled: false,
        cooldownSeconds: 120,
        maxEventsPerHour: 20,
        retentionDays: 30,
        maxEvents: 5000,
        cameras: Object.fromEntries(
          ["01", "02", "03", "04", "05", "06", "07", "08"].map((id) => [
            id,
            {
              enabled: !["02", "07"].includes(id),
              threshold: 0.8,
              minArea: 0.007,
              maxArea: id === "05" ? 0.1 : 0.99,
              minTravel: id === "05" ? 0.04 : id === "06" ? 0.02 : 0.03,
            },
          ]),
        ),
      },
    }),
  );
  await page.route("**/api/animals/events?limit=40", (route) =>
    route.fulfill({
      json: {
        events: [
          {
            id: "event-1",
            cameraId: "05",
            cameraName: "Front Drive",
            startedAt: 1788750000,
            endedAt: null,
            confidence: 0.91,
            boundingBox: [0.1, 0.1, 0.4, 0.4],
            travelPercent: 0.05,
            pathPoints: 4,
            hasSnapshot: true,
            snapshotUrl: "/icon.svg",
            alertStatus: "shadow",
            alertAttempts: 0,
            suppressed: false,
            acknowledgedAt: null,
          },
        ],
      },
    }),
  );
  await page.route("**/api/animals/events", (route) =>
    route.fulfill({
      json: {
        cleared: 1,
        frigateEventsDeleted: 1,
        frigateDeleteFailures: 0,
      },
    }),
  );
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/?tab=animals");
  await expect(page.getByText("Front Drive", { exact: true })).toBeVisible();
  await expect(page.getByText("91% MATCH")).toBeVisible();
  const hourlyLimit = page.getByLabel("Maximum animal events per hour");
  await expect(hourlyLimit).toBeVisible();
  await expect(hourlyLimit).toHaveValue("20");
  await page.route("**/api/animals/hourly-counts/reset", (route) =>
    route.fulfill({ json: { reset: 1 } }),
  );
  const resetRequest = page.waitForRequest((request) =>
    request.url().endsWith("/api/animals/hourly-counts/reset") && request.method() === "POST",
  );
  await page.getByRole("button", { name: "Reset hourly counts" }).click();
  await resetRequest;
  await expect(page.getByText("Hourly counts reset for all cameras. Existing events were kept.")).toBeVisible();
  await expect(page.getByText("91% MATCH")).toBeVisible();
  await hourlyLimit.fill("5");
  const savedLimit = page.waitForRequest((request) =>
    request.url().endsWith("/api/animals/settings") && request.method() === "PATCH",
  );
  await hourlyLimit.blur();
  expect((await savedLimit).postDataJSON()).toEqual({ maxEventsPerHour: 5 });
  await expect(page.getByText("Shadow mode")).toBeVisible();
  await expect(page.getByText("5% movement")).toBeVisible();
  await expect(page.getByLabel("Front Drive confidence")).toHaveValue("80");
  await expect(page.getByLabel("Front Drive maximum area")).toHaveValue("10");
  await expect(page.getByLabel("Front Drive minimum movement")).toHaveValue(
    "4",
  );
  const perCameraConfidence = page.getByLabel("Front Drive confidence");
  await perCameraConfidence.fill("25");
  const confidenceSave = page.waitForRequest((request) =>
    request.url().endsWith("/api/animals/settings") && request.method() === "PATCH",
  );
  await perCameraConfidence.blur();
  expect((await confidenceSave).postDataJSON()).toEqual({ cameras: { "05": { threshold: 0.25 } } });
  await page.getByLabel("Confidence for all cameras").fill("70");
  const globalSave = page.waitForRequest((request) =>
    request.url().endsWith("/api/animals/settings") && request.method() === "PATCH",
  );
  await page.getByRole("button", { name: "Apply to all cameras" }).click();
  const globalBody = (await globalSave).postDataJSON();
  expect(Object.keys(globalBody.cameras)).toHaveLength(7);
  expect(globalBody.cameras["05"].threshold).toBe(0.70);
  let quality = { profile: "360p", fps: 2, width: 640, height: 360, stream: "2" };
  await page.route("**/api/animals/quality/05", (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({ profile: "720p", fps: 2 });
      quality = { profile: "720p", fps: 2, width: 1280, height: 720, stream: "0" };
      return route.fulfill({json:{...quality, restartRequested:true, message:"Saved. Frigate is restarting."}});
    }
    return route.fulfill({json:quality});
  });
  await page.getByRole("button", {name:"Detection quality / Front Drive"}).click();
  const qualityDialog = page.getByRole("dialog", {name:"Detection quality / Front Drive"});
  await expect(qualityDialog.getByLabel("Detection resolution")).toHaveValue("360p");
  await qualityDialog.getByLabel("Detection resolution").selectOption("720p");
  await qualityDialog.getByRole("button", {name:"Save and restart Frigate"}).click();
  await expect(qualityDialog.getByRole("status")).toContainText("Frigate is restarting");
  await qualityDialog.getByRole("button", {name:"Close",exact:true}).click();
  let masks: string[] = [];
  let rejectMasks = false;
  await page.route("**/api/animals/masks/05", async (route) => {
    if (route.request().method() === "POST") {
      if (rejectMasks) return route.fulfill({ status: 503, json: { error: "Frigate unavailable" } });
      masks = route.request().postDataJSON().masks;
    }
    return route.fulfill({ json: { masks } });
  });
  let snapshotAttempts = 0;
  let snapshotUnavailable = true;
  await page.route("**/api/snapshot/05?*", (route) => {
    snapshotAttempts += 1;
    if (snapshotUnavailable) return route.fulfill({
      status: 503, json: { error: "Recorder snapshot timed out. Retry the capture." },
    });
    return route.fulfill({
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#334433"/></svg>',
    });
  });
  await page.getByRole("button", { name: "Edit masks / Front Drive" }).click();
  const maskDialog = page.getByRole("dialog", { name: "Animal masks / Front Drive" });
  await expect(maskDialog.getByRole("alert")).toContainText("Recorder snapshot timed out");
  await expect(maskDialog.getByRole("button", { name: "Save masks" })).toBeDisabled();
  snapshotUnavailable = false;
  await maskDialog.getByRole("button", { name: "Refresh image", exact: true }).click();
  await expect(maskDialog.getByRole("button", { name: "Refresh image", exact: true })).toBeEnabled();
  await expect(maskDialog.getByRole("alert")).toHaveCount(0);
  await expect(maskDialog.getByText("Loading camera snapshot…")).toHaveCount(0);
  expect(snapshotAttempts).toBeGreaterThanOrEqual(2);
  const canvas = maskDialog.getByRole("img", { name: "Draw animal masks" });
  await canvas.click({ position: { x: 20, y: 20 } });
  await canvas.click({ position: { x: 80, y: 20 } });
  await canvas.click({ position: { x: 80, y: 70 } });
  await maskDialog.getByRole("button", { name: "Finish polygon" }).click();
  await canvas.click({ position: { x: 130, y: 30 } });
  await canvas.click({ position: { x: 180, y: 30 } });
  await canvas.click({ position: { x: 180, y: 80 } });
  await maskDialog.getByRole("button", { name: "Finish polygon" }).click();
  await maskDialog.getByRole("button", { name: "Save masks" }).click();
  await expect(maskDialog.getByRole("status")).toContainText("Masks saved");
  expect(masks).toHaveLength(2);
  expect(masks[0].split(",").map(Number).every((v) => v >= 0 && v <= 1)).toBeTruthy();
  await maskDialog.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Edit masks / Front Drive" }).click();
  await expect(maskDialog.getByRole("button", { name: "Mask 2", exact: true })).toBeVisible();
  await maskDialog.getByRole("button", { name: "Clear masks", exact: true }).click();
  rejectMasks = true;
  await maskDialog.getByRole("button", { name: "Save masks" }).click();
  await expect(maskDialog.getByRole("alert")).toContainText("Frigate unavailable");
  expect(masks).toHaveLength(2);
  rejectMasks = false;
  await maskDialog.getByRole("button", { name: "Save masks" }).click();
  await expect(maskDialog.getByRole("status")).toContainText("Masks saved");
  expect(masks).toHaveLength(0);
  await maskDialog.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: /Animal at Front Drive/ }).click();
  await page.getByRole("button", { name: "Play recording" }).click();
  const cameraDialog = page.locator(".camera-dialog");
  await expect(cameraDialog).toBeVisible();
  await expect(
    cameraDialog.getByRole("heading", { name: "Front Drive" }),
  ).toBeVisible();
  await expect(
    cameraDialog.getByText("Playback begins 5 seconds before this time."),
  ).toBeVisible();
  await expect(cameraDialog.locator("video")).toHaveAttribute(
    "src",
    /\/api\/playback\/05\?at=1788750000/,
  );
  await cameraDialog.getByRole("button", { name: "Close camera" }).click();
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(
    page.getByRole("heading", { name: "No animals logged" }),
  ).toBeVisible();
  await expect(
    page.getByText("Cleared 1 animal events and their metadata. Hourly counts reset."),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("stream routes restrict channel and filename and keep credentials private", async ({
  request,
}) => {
  expect((await request.get("/api/stream/99/index.m3u8")).status()).toBe(404);
  expect((await request.get("/api/stream/01/secrets.txt")).status()).toBe(404);
  expect((await request.get("/api/snapshot/99")).status()).toBe(404);
  expect((await request.get("/api/snapshot/01")).status()).toBe(503);
  expect((await request.get("/api/playback/99?at=1788750000")).status()).toBe(
    404,
  );
  expect((await request.get("/api/playback/01")).status()).toBe(400);
  const response = await request.get("/api/stream/01/index.m3u8");
  expect(response.status()).toBe(503);
  expect(response.headers()["cache-control"]).toBe("no-store");
  const health = await (await request.get("/api/health")).json();
  expect(health.configured).toBe(false);
  expect(health.animals).toBeNull();
  expect(health).not.toHaveProperty("password");
});

test("dashboard retains good frames and recovers from slow fallback snapshots", async ({ page }) => {
  await page.route("**/api/health", route => route.fulfill({json:{configured:true,host:"recorder.local",animals:null}}));
  await page.route("**/api/snapshot/**", route => route.fulfill({status:503,json:{error:"Unavailable"}}));
  let source="recorder";
  let fail=false;
  let failedResponses=0;
  await page.route("**/api/snapshot/01?*", async route => {
    if(fail){await route.fulfill({status:503,json:{error:"Unavailable"}});failedResponses++;return;}
    // Longer than the dashboard's old global tick: this must still render.
    await new Promise(resolve=>setTimeout(resolve,1300));
    await route.fulfill({contentType:"image/svg+xml",headers:{"X-Snapshot-Source":source},
      body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#334433"/></svg>'});
  });
  await page.goto("/");
  const image=page.getByRole("img",{name:"Latest snapshot from Front Door"});
  await expect(image).toBeVisible();
  await expect(page.getByText("RECORDER PREVIEW",{exact:true})).toHaveCount(1);
  const previous=await image.getAttribute("src");
  fail=true;
  await expect.poll(()=>failedResponses).toBeGreaterThan(0);
  await expect(image).toHaveAttribute("src",previous!);
  source="frigate";fail=false;
  await expect(page.getByText("RECORDER PREVIEW",{exact:true})).toHaveCount(0);
  await expect(image).toBeVisible();
});

test("System reports CPU averages, warmup, refresh and unavailable state", async ({page}) => {
  let mode="ready";
  let requests=0;
  await page.route("**/api/system/cpu", route => {
    requests++;
    if(mode==="error")return route.fulfill({status:503,json:{error:"Unavailable"}});
    return route.fulfill({json:{available:true,currentPercent:mode==="warm"?null:42.5,averagePercent:mode==="warm"?null:31.2,
      samples:mode==="warm"?0:12,coverageSeconds:mode==="warm"?0:60,sampleIntervalSeconds:5,windowSeconds:60,cpuCount:8,sampledAt:Date.now()/1000,scope:"Linux host / Docker VM"}});
  });
  await page.goto("/");
  await page.getByRole("navigation",{name:"Mobile navigation"}).getByRole("button",{name:"System"}).click();
  await expect(page.getByRole("heading",{name:"Server CPU"})).toBeVisible();
  await expect(page.getByLabel("Latest CPU usage",{exact:true})).toHaveText("42.5%");
  await expect(page.getByLabel("Average CPU usage",{exact:true})).toHaveText("31.2%");
  await expect(page.getByText("12/12 samples · 60s coverage · 8 logical CPUs")).toBeVisible();
  mode="error";
  await expect(page.getByText("CPU statistics unavailable. Retrying every 5 seconds.")).toBeVisible({timeout:10000});
  await expect(page.getByLabel("Average CPU usage",{exact:true})).toHaveText("—");
  mode="warm";
  await expect(page.getByText("Collecting the first CPU sample…")).toBeVisible({timeout:10000});
  expect(requests).toBeGreaterThanOrEqual(3);
});

test("notification playback links open the original recording without event metadata", async ({page}) => {
  await page.route("**/api/health",route=>route.fulfill({json:{configured:true,host:"recorder.local",animals:null}}));
  await page.route("**/api/animals/settings",route=>route.fulfill({json:{globalEnabled:true,alertsEnabled:false,cooldownSeconds:30,maxEventsPerHour:5,cameras:{}}}));
  await page.route("**/api/animals/events?*",route=>route.fulfill({json:{events:[],nextBefore:null}}));
  let eventLookups=0;
  await page.route("**/api/animals/events/cleared-event",route=>{eventLookups++;return route.fulfill({status:404,json:{error:"Unknown event"}});});
  await page.route("**/api/playback/**",route=>route.fulfill({status:200,contentType:"video/mp4",body:Buffer.from([])}));
  await page.goto("/?tab=animals&event=cleared-event&playback=1&camera=05&at=1788764730");
  const dialog=page.locator(".camera-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading",{name:"Front Drive"})).toBeVisible();
  await expect(dialog.locator("video")).toHaveAttribute("src",/\/api\/playback\/05\?at=1788764730/);
  await expect(dialog.getByText("Playback begins 5 seconds before this time.")).toBeVisible();
  await expect(page.locator(".animal-dialog")).not.toBeVisible();
  expect(eventLookups).toBe(0);
  await dialog.getByRole("button",{name:"Close camera"}).click();
  await expect(dialog).not.toBeVisible();
});

test("invalid notification links never fall back to current-time playback",async({page})=>{
  let playbackRequests=0;
  await page.route("**/api/playback/**",route=>{playbackRequests++;return route.fulfill({status:400,json:{error:"Invalid playback time"}});});
  await page.goto("/?tab=animals&playback=1&camera=05&at=not-a-time");
  await expect(page.getByRole("alert").filter({hasText:"This playback link is invalid"})).toBeVisible();
  await expect(page.locator(".camera-dialog")).not.toBeVisible();
  expect(playbackRequests).toBe(0);
});

test("event details deep links resolve outside the latest event list and report missing events",async({page})=>{
  await page.route("**/api/animals/settings",route=>route.fulfill({json:{globalEnabled:true,alertsEnabled:false,cooldownSeconds:30,maxEventsPerHour:5,cameras:{}}}));
  await page.route("**/api/animals/events?*",route=>route.fulfill({json:{events:[],nextBefore:null}}));
  await page.route("**/api/animals/events/older-event",route=>route.fulfill({json:{id:"older-event",cameraId:"05",cameraName:"Front Drive",startedAt:1788764730,endedAt:1788764740,confidence:0.91,boundingBox:[0.1,0.1,0.2,0.2],travelPercent:0,hasSnapshot:true,snapshotUrl:"/icon.svg",alertStatus:"sent",alertAttempts:1,suppressed:false,acknowledgedAt:null}}));
  await page.goto("/?tab=animals&event=older-event");
  const dialog=page.locator(".animal-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading",{name:"Front Drive"})).toBeVisible();
  await dialog.getByRole("button",{name:"Close animal event"}).click();
  await expect(dialog).not.toBeVisible();
  await page.route("**/api/animals/events/missing-event",route=>route.fulfill({status:404,json:{error:"Unknown event"}}));
  await page.goto("/?tab=animals&event=missing-event");
  await expect(page.getByRole("alert").filter({hasText:"This event is no longer in Sentinel history"})).toBeVisible();
  await expect(page.locator(".animal-dialog")).not.toBeVisible();
});
