import Link from "next/link";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <header style={{ display: "flex", gap: 16, padding: "12px 24px", borderBottom: "1px solid #e5e5e5" }}>
        <strong>TripPlanner</strong>
        <Link href="/trips">내 여행</Link>
        <Link href="/notifications">알림</Link>
        <Link href="/mypage">마이페이지</Link>
      </header>
      {children}
    </div>
  );
}
