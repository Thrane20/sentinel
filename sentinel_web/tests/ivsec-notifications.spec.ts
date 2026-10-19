import { expect, test } from "@playwright/test";

const event = {
  id: 42,
  cameraId: "04",
  cameraName: "Garage",
  eventType: "Perimeter intrusion",
  eventKey: "perimeter_intrusion",
  sourceTime: "10/19/2026 09:15:00",
  observedAt: 1792365300,
  collectedAt: 1792365302,
  source: "live",
  raw: { int_alarm: { alarm_val: true, int_subtype: "pid" } },
  deliveries: [],
};

test("IVSEC rule and test mutations reject other origins", async ({
  request,
}) => {
  for (const path of [
    "/api/ivsec/notification-rules",
    "/api/ivsec/notification-test",
  ]) {
    const response = await request.post(path, {
      headers: { Origin: "http://untrusted-host" },
      data: {},
    });
    expect(response.status()).toBe(403);
  }
  const invalid = await request.get("/api/ivsec/events/not-an-id");
  expect(invalid.status()).toBe(400);
});

test("inspect an IVSEC subtype and create, test, edit and delete its camera-specific rule", async ({
  page,
}) => {
  let rules: Record<string, unknown>[] = [];
  await page.route("**/api/ivsec/events", (route) =>
    route.fulfill({
      json: {
        events: [{ ...event, capturedAt: event.observedAt }],
        health: { online: true, configured: true },
      },
    }),
  );
  await page.route("**/api/ivsec/events/42", (route) =>
    route.fulfill({ json: event }),
  );
  await page.route("**/api/ivsec/notification-rules", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      expect(body.cameraId).toBe("04");
      expect(body.eventKey).toBe("perimeter_intrusion");
      rules = [body];
      return route.fulfill({ json: body });
    }
    return route.fulfill({
      json: {
        rules,
        webhookConfigured: true,
        catalog: [
          {
            cameraId: "04",
            eventKey: "perimeter_intrusion",
            eventType: "Perimeter intrusion",
          },
        ],
      },
    });
  });
  await page.route("**/api/ivsec/notification-test", (route) => {
    expect(route.request().postDataJSON()).toEqual({
      eventId: 42,
      ruleId: "garage_intrusion",
    });
    return route.fulfill({ status: 202, json: { queued: 1 } });
  });
  await page.route(
    "**/api/ivsec/notification-rules/garage_intrusion",
    (route) => {
      rules = [];
      return route.fulfill({ json: { deleted: true } });
    },
  );
  await page.goto("/?tab=playback");
  await page
    .getByRole("button", { name: "Inspect IVSEC event 42", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "IVSEC event inspector" }),
  ).toBeVisible();
  await expect(dialog.locator("pre")).toContainText('"int_subtype": "pid"');
  await dialog
    .getByRole("button", { name: "Create notification rule", exact: true })
    .click();
  await expect(page.getByLabel("IVSEC event key")).toHaveValue(
    "perimeter_intrusion",
  );
  await expect(
    page.getByLabel("Enable automatic delivery for this rule"),
  ).not.toBeChecked();
  await page
    .getByLabel("Notification ID", { exact: true })
    .fill("garage_intrusion");
  await page
    .getByLabel("Notification message", { exact: true })
    .fill("Something is moving in the garage");
  await page.getByLabel("Enable automatic delivery for this rule").check();
  await page
    .getByRole("button", { name: "Save notification rule", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Saved garage_intrusion",
  );
  await page
    .getByRole("button", { name: "Inspect IVSEC event 42", exact: true })
    .click();
  await dialog
    .getByRole("button", {
      name: "Send HA test / garage_intrusion",
      exact: true,
    })
    .click();
  await expect(dialog.getByRole("status")).toContainText("Test queued");
  await dialog
    .getByRole("button", { name: "Close IVSEC event inspector" })
    .click();
  await page
    .getByRole("button", { name: "Edit garage_intrusion", exact: true })
    .click();
  await expect(
    page.getByLabel("Notification ID", { exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Delete garage_intrusion", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Edit garage_intrusion", exact: true }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("IVSEC inspection links fetch an event outside the latest list and report cleared metadata", async ({
  page,
}) => {
  await page.route("**/api/ivsec/events", (route) =>
    route.fulfill({ json: { events: [], health: { online: true } } }),
  );
  await page.route("**/api/ivsec/events/42", (route) =>
    route.fulfill({ json: event }),
  );
  await page.goto("/?tab=playback&ivsecEvent=42");
  await expect(
    page.getByRole("dialog").getByText("Perimeter intrusion · Garage"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Close IVSEC event inspector" })
    .click();
  await page.route("**/api/ivsec/events/99", (route) =>
    route.fulfill({
      status: 404,
      json: { error: "Event was cleared or is no longer available." },
    }),
  );
  await page.goto("/?tab=playback&ivsecEvent=99");
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "cleared",
  );
});

test("IVSEC playback notification retains its camera/time without requiring event metadata", async ({
  page,
}) => {
  await page.route("**/api/playback/04?*", (route) =>
    route.fulfill({ status: 404, json: { error: "Recording unavailable" } }),
  );
  await page.goto(
    "/?tab=playback&ivsecEvent=cleared&playback=1&camera=04&at=1792365300",
  );
  await expect(page.locator(".camera-dialog")).toBeVisible();
  await expect(page.locator(".camera-dialog video")).toHaveAttribute(
    "src",
    /\/api\/playback\/04\?at=1792365300/,
  );
});
