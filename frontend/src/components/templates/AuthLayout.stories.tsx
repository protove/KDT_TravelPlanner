import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "@/components/atoms/Button";
import { AuthLayout } from "./AuthLayout";

const meta = {
  title: "Templates/AuthLayout",
  component: AuthLayout,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof AuthLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { children: null },
  render: () => (
    <AuthLayout>
      <div className="flex flex-col items-center gap-6 text-center">
        <div className="flex items-center gap-2.5">
          <span className="flex h-[30px] w-[30px] items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
            T
          </span>
          <span className="text-base font-bold text-foreground">TripPlanner</span>
        </div>
        <p className="text-sm text-muted-foreground">SSO로 간편하게 시작하세요</p>
        <div className="flex w-full flex-col gap-2">
          <Button className="w-full">구글로 계속하기</Button>
          <Button variant="outline" className="w-full">
            네이버로 계속하기
          </Button>
        </div>
      </div>
    </AuthLayout>
  ),
};
