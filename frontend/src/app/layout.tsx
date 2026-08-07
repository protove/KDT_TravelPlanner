import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/providers/AuthProvider";
import { HeaderLayout } from "@/components/providers/HeaderLayout";

export const metadata: Metadata = {
  title: "TripPlanner",
  description: "TripPlanner development environment status",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <AuthProvider>
          <HeaderLayout>{children}</HeaderLayout>
        </AuthProvider>
      </body>
    </html>
  );
}
