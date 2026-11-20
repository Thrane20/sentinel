import "@fontsource-variable/inter";
import type { Metadata, Viewport } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "SENTINEL / Security command",
  icons: { icon: "/icon.svg" },
  description: "Your local IVSEC camera console",
  appleWebApp: {
    capable: true,
    title: "Sentinel",
    statusBarStyle: "default",
  },
};
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#e8edf3",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
