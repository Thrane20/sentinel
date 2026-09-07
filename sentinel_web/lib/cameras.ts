export const cameras = [
  { id: "01", name: "Front Door", zone: "Entry", seen: true },
  { id: "03", name: "Pool", zone: "Outdoor", seen: true },
  { id: "04", name: "Garage", zone: "Entry", seen: true },
  { id: "05", name: "Front Drive", zone: "Entry", seen: true },
  { id: "06", name: "Backyard - Down", zone: "Outdoor", seen: true },
  { id: "08", name: "Side Passage", zone: "Outdoor", seen: true },
  { id: "02", name: "Backyard - Up", zone: "Outdoor", seen: false },
  { id: "07", name: "Boat Shed", zone: "Outdoor", seen: false },
];
export type Camera = (typeof cameras)[number];
