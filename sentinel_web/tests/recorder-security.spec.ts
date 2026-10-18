import { expect, test } from "@playwright/test";

const armed = {
  online: true,
  disarming: false,
  armed: true,
  checkedAt: 1792300000,
};
const disarmed = { ...armed, disarming: true, armed: false };

test("home arming control waits for recorder confirmation in both directions", async ({
  page,
}) => {
  let current = armed;
  let release: (() => void) | undefined;
  await page.route("**/api/ivsec/security", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON();
      expect(body).toEqual({
        disarming: !current.disarming,
        expectedDisarming: current.disarming,
      });
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      current = body.disarming ? disarmed : armed;
    }
    await route.fulfill({ json: current });
  });
  await page.goto("/");
  const controls = page.getByLabel("IVSEC arming controls");
  await expect(controls.getByRole("status")).toHaveText("Armed");
  await controls
    .getByRole("button", { name: "Disarm IVSEC", exact: true })
    .click();
  await expect(
    controls.getByRole("button", { name: "Updating IVSEC…" }),
  ).toBeDisabled();
  await expect(controls.getByRole("status")).toHaveText("Armed");
  await expect.poll(() => !!release).toBe(true);
  release!();
  await expect(controls.getByRole("status")).toHaveText("Disarmed");
  await expect(controls.locator(".recorder-arm-status")).toHaveClass(
    /disarmed/,
  );
  release = undefined;
  await controls
    .getByRole("button", { name: "Arm IVSEC", exact: true })
    .click();
  await expect.poll(() => !!release).toBe(true);
  release!();
  await expect(controls.getByRole("status")).toHaveText("Armed");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("failed changes clear the armed indicator and allow status recovery", async ({
  page,
}) => {
  await page.route("**/api/ivsec/security", (route) =>
    route.fulfill(
      route.request().method() === "PATCH"
        ? {
            status: 503,
            json: { error: "Recorder did not confirm the requested state." },
          }
        : { json: armed },
    ),
  );
  await page.goto("/");
  const controls = page.getByLabel("IVSEC arming controls");
  await controls
    .getByRole("button", { name: "Disarm IVSEC", exact: true })
    .click();
  await expect(controls.getByRole("status")).toHaveText("Status unavailable");
  await expect(controls.getByRole("alert")).toContainText("did not confirm");
  await expect(
    controls.getByRole("button", { name: "Disarm IVSEC", exact: true }),
  ).toHaveCount(0);
  await controls
    .getByRole("button", { name: "Refresh IVSEC arming status" })
    .click();
  await expect(controls.getByRole("status")).toHaveText("Armed");
});

test("home polls changes made outside Sentinel", async ({ page }) => {
  let current = armed;
  await page.clock.install();
  await page.route("**/api/ivsec/security", (route) =>
    route.fulfill({ json: current }),
  );
  await page.goto("/");
  const status = page.getByLabel("IVSEC arming controls").getByRole("status");
  await expect(status).toHaveText("Armed");
  current = disarmed;
  await page.clock.runFor(10100);
  await expect(status).toHaveText("Disarmed");
});

test("recorder changes reject cross-origin and malformed requests", async ({
  request,
}) => {
  const denied = await request.patch("/api/ivsec/security", {
    headers: { Origin: "http://other-host" },
    data: { disarming: true, expectedDisarming: false },
  });
  expect(denied.status()).toBe(403);
  const invalid = await request.patch("/api/ivsec/security", {
    data: { disarming: "true" },
  });
  expect(invalid.status()).toBe(400);
});
