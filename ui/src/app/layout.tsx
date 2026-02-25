import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Flowise Dev Agent", description: "Co-pilot for building Flowise chatflows" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background font-sans antialiased">{children}</body>
    </html>
  );
}
