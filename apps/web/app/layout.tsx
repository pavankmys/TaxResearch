import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'TaxResearch POC',
  description: 'GST Tax Research Assistant - POC',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
