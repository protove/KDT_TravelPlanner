import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { AppHeader } from "@/components/organisms/AppHeader";
import { Button } from "@/components/atoms/Button";
import { LandingLayout } from "./LandingLayout";

const meta = {
  title: "Templates/LandingLayout",
  component: LandingLayout,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof LandingLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { children: null },
  render: () => (
    <LandingLayout header={<AppHeader loggedIn={false} />}>
      <h1 className="text-3xl font-bold text-foreground">여행 일정을 함께 계획하세요</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        친구, 가족과 함께 지도 위에서 여행 일정을 짜고 실시간으로 공유해보세요.
      </p>
      <Button size="lg">시작하기</Button>
    </LandingLayout>
  ),
};
