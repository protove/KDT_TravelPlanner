import Link from "next/link";

export default function ForbiddenPage() {
  return (
    <main style={{ padding: 40 }}>
      <h1>접근할 수 없는 페이지입니다</h1>
      <p>권한이 없거나 삭제된 항목이거나 잘못된 주소입니다.</p>
      <Link href="/trips">여행 목록으로</Link>
    </main>
  );
}
