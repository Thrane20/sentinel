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
  expect(headerBox && summaryBox && summaryBox.y >= headerBox.y + headerBox.height).toBe(true);
  await page.getByRole("button", { name: "Entry", exact: true }).click();
  await expect(page.locator(".camera-card")).toHaveCount(3);
  await page.getByRole("button", { name: "All cameras", exact: true }).click();
  await page
    .getByRole("button", { name: "Include previously offline cameras" })
    .click();
  await expect(page.locator(".camera-card")).toHaveCount(6);
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
  await expect(page.getByRole("button", { name: "Close camera" })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "Front Door" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close camera" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(camera).toBeFocused();
});
test("playback lists and clears collected IVSEC alerts", async ({
  page,
}) => {
  let cleared = false;
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
                capturedAt: 1788750330,
              },
            ],
        health: {
          online: true,
          configured: true,
          lastPoll: 1788750330,
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
  await expect(page.getByRole("heading", { name: "IVSEC alerts" })).toBeVisible();
  await expect(page.getByText("Recorder feed connected")).toBeVisible();
  await expect(page.getByText("Motion", { exact: true })).toBeVisible();
  await expect(page.getByText("CH 05", { exact: true })).toBeVisible();
  await expect(page.getByText("Front Drive", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No collected alerts" })).toBeVisible();
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
  await expect(page.getByText("Animal detection services are not available yet."))
    .toBeVisible();
  await expect(page.getByRole("heading", { name: "No animals logged" }))
    .toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("animal event cards and controls render from the local service", async ({
  page,
}) => {
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
  await expect(page.getByText("Shadow mode")).toBeVisible();
  await expect(page.getByText("5% movement")).toBeVisible();
  await expect(page.getByLabel("Front Drive confidence")).toHaveValue("80");
  await expect(page.getByLabel("Front Drive maximum area")).toHaveValue("10");
  await expect(page.getByLabel("Front Drive minimum movement")).toHaveValue("4");
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page.getByRole("heading", { name: "No animals logged" })).toBeVisible();
  await expect(page.getByText("Cleared 1 animal events and their metadata.")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
test("stream routes restrict channel and filename and keep credentials private", async ({
  request,
}) => {
  expect((await request.get("/api/stream/99/index.m3u8")).status()).toBe(404);
  expect((await request.get("/api/stream/01/secrets.txt")).status()).toBe(404);
  expect((await request.get("/api/snapshot/99")).status()).toBe(404);
  expect((await request.get("/api/snapshot/01")).status()).toBe(503);
  const response = await request.get("/api/stream/01/index.m3u8");
  expect(response.status()).toBe(503);
  expect(response.headers()["cache-control"]).toBe("no-store");
  const health = await (await request.get("/api/health")).json();
  expect(health.configured).toBe(false);
  expect(health.animals).toBeNull();
  expect(health).not.toHaveProperty("password");
});
