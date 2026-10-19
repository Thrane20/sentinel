export const recorderDays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const time = (slot: number) =>
  `${String(Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 ? "30" : "00"}`;
export function formatSlots(slots: number[]) {
  const spans: string[] = [];
  for (let i = 0; i < 48; i++) {
    if (!slots[i]) continue;
    const start = i;
    while (i < 48 && slots[i]) i++;
    spans.push(`${time(start)}-${time(i)}`);
  }
  return spans.join(", ");
}
export function parseSlots(text: string) {
  const slots = Array<number>(48).fill(0);
  if (!text.trim()) return slots;
  for (const span of text.split(",")) {
    const match = span.trim().match(/^(\d{2}):(00|30)\s*-\s*(\d{2}):(00|30)$/);
    if (!match)
      throw new Error(
        "Use half-hour ranges such as 00:00-06:00, 19:00-24:00. Leave blank for off all day.",
      );
    const start = Number(match[1]) * 2 + Number(match[2]) / 30;
    const end = Number(match[3]) * 2 + Number(match[4]) / 30;
    if (start >= 48 || end > 48 || start === end)
      throw new Error(
        "Use times from 00:00 to 24:00, with different start and end times.",
      );
    for (let i = 0; i < 48; i++) {
      if (start < end ? i >= start && i < end : i >= start || i < end)
        slots[i] = 1;
    }
  }
  return slots;
}
