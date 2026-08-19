"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { ListLayout } from "@/components/templates/ListLayout";

export default function CommunityPage() {
  const router = useRouter();

  return (
    <ListLayout
      title={<h1 className="text-2xl font-bold text-foreground">커뮤니티</h1>}
      actions={
        <Button onClick={() => router.push("/community/write")}>+ 글쓰기</Button>
      }
    >
      <p className="text-sm text-muted-foreground">
        공개된 여행 일정을 둘러보는 화면입니다.
      </p>
    </ListLayout>
  );
}
