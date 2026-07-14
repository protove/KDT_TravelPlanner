import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Travel Diary",
  description: "Travel Diary development environment status",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
