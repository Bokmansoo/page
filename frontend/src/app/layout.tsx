import type { Metadata } from "next";
import { Inter, Outfit } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const outfit = Outfit({ subsets: ["latin"], variable: "--font-outfit" });

export const metadata: Metadata = {
  title: "Sellform - AI 상품 콘텐츠 스튜디오",
  description: "공급처 자료를 판매 가능한 고품질 상세페이지 및 마케팅 문구로 자동 생성하는 AI 상품 콘텐츠 스튜디오",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className={`${inter.variable} ${outfit.variable} dark`}>
      <body className="antialiased selection:bg-indigo-500/30">
        {children}
      </body>
    </html>
  );
}
