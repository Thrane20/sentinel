import { expect, test } from "@playwright/test";
import { formatSlots, parseSlots, recorderDays } from "../lib/ivsec-schedule";

test("half-hour schedules retain multiple periods, midnight, and off days", () => {
  expect(formatSlots(parseSlots("00:00-06:00, 19:00-24:00"))).toBe(
    "00:00-06:00, 19:00-24:00",
  );
  expect(parseSlots("19:00-06:00")).toEqual(
    parseSlots("00:00-06:00, 19:00-24:00"),
  );
  expect(formatSlots(parseSlots(""))).toBe("");
  expect(formatSlots(parseSlots("00:00-24:00"))).toBe("00:00-24:00");
  for (const value of [
    "25:00-06:00",
    "10:15-11:30",
    "19:00-24:30",
    "06:00-06:00",
  ])
    expect(() => parseSlots(value)).toThrow();
});

async function mockRecorder(
  page: import("@playwright/test").Page,
  fail = false,
) {
  const writes: Record<string, unknown>[] = [];
  await page.route("**/api/ivsec/remote**", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.has("catalog"))
      return route.fulfill({
        json: {
          events: [
            { id: "PID", label: "Perimeter intrusion" },
            { id: "Motion", label: "Motion" },
          ],
        },
      });
    const patch = route.request().method() === "PATCH";
    const body = patch ? route.request().postDataJSON() : null;
    const section = patch ? body.section : url.searchParams.get("section");
    if (patch) {
      writes.push(body);
      if (fail)
        return route.fulfill({
          status: 409,
          json: { error: "Settings changed elsewhere. Reload before saving." },
        });
    }
    const schedule = section?.endsWith("Schedule")
      ? body?.values || {
          enabled: true,
          week: recorderDays.map((day) => ({ day, time: Array(48).fill(1) })),
        }
      : null;
    return route.fulfill({
      json: {
        supported: true,
        revision: "version1",
        fields:
          section === "detection"
            ? [
                {
                  key: "switch",
                  label: "Detection enabled",
                  value: patch ? body.values.switch : true,
                  disabled: false,
                  schema: { type: "bool" },
                },
              ]
            : [],
        schedule,
      },
    });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "System", exact: true })
    .first()
    .click();
  return writes;
}

test("camera event settings save only changed fields and confirm the recorder reply", async ({
  page,
}) => {
  const writes = await mockRecorder(page);
  const panel = page.getByLabel("IVSEC remote settings");
  await panel.getByRole("combobox", { name: "Camera", exact: true }).selectOption("05");
  const detection = panel.getByRole("region", {
    name: "Event detection",
    exact: true,
  });
  await detection.getByLabel("Detection enabled").uncheck();
  await detection.getByRole("button", { name: "Save event detection" }).click();
  await expect(detection.getByRole("status")).toHaveText(
    "Saved and confirmed by IVSEC.",
  );
  expect(writes).toEqual([
    {
      camera: "05",
      event: "PID",
      section: "detection",
      revision: "version1",
      values: { switch: false },
    },
  ]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("output schedule supports distinct days, multiple periods, and disabled triggers", async ({
  page,
}) => {
  const writes = await mockRecorder(page);
  const schedule = page.getByRole("region", {
    name: "Siren schedule",
    exact: true,
  });
  await schedule
    .getByRole("button", { name: "Night (19:00–06:00)", exact: true })
    .click();
  await schedule.getByLabel("Siren schedule Sun", { exact: true }).fill("");
  await schedule
    .getByLabel("Enable this event to trigger the output")
    .uncheck();
  await schedule.getByRole("button", { name: "Save siren schedule" }).click();
  await expect(schedule.getByRole("status")).toHaveText(
    "Saved and confirmed by IVSEC.",
  );
  const values = writes[0].values as {
    enabled: boolean;
    week: { day: string; time: number[] }[];
  };
  expect(values.enabled).toBe(false);
  expect(values.week[0].time).toEqual(Array(48).fill(0));
  expect(values.week[1].time).toEqual(parseSlots("00:00-06:00,19:00-24:00"));
});

test("conflict requires reload and never displays a successful save", async ({
  page,
}) => {
  await mockRecorder(page, true);
  const detection = page.getByRole("region", {
    name: "Event detection",
    exact: true,
  });
  await detection.getByLabel("Detection enabled").uncheck();
  await detection.getByRole("button", { name: "Save event detection" }).click();
  await expect(detection.getByRole("alert")).toContainText("changed elsewhere");
  await expect(
    detection.getByRole("button", { name: "Save event detection" }),
  ).toHaveCount(0);
  await detection.getByRole("button", { name: "Reload", exact: true }).click();
  await expect(detection.getByLabel("Detection enabled")).toBeChecked();
});

test("remote settings rejects cross-origin recorder changes", async ({
  request,
}) => {
  const response = await request.patch("/api/ivsec/remote", {
    headers: { Origin: "http://untrusted.example" },
    data: {},
  });
  expect(response.status()).toBe(403);
});
