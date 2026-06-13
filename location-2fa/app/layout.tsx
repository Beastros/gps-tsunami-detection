import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Location 2FA",
  description: "Location-aware multi-factor authentication",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
