import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Top Picks Screener",
  description:
    "Dashboard interaktif undervalued picks — IDX, US, dan Crypto dari screener-auto.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="id">
      <body>{children}</body>
    </html>
  );
}
