"use client";

import { ListLayout } from "@/components/templates/ListLayout";

export default function CommunityPage() {
  return (
    <ListLayout
      title={<h1 className="text-2xl font-bold text-foreground">커뮤니티</h1>}
    >
      <p className="text-sm text-muted-foreground">
        공개된 여행 일정을 둘러보는 화면입니다.
      </p>
    </ListLayout>
  );
}
