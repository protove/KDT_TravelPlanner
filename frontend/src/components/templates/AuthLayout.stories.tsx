import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { SocialLoginButton } from "@/components/molecules/SocialLoginButton";
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
      <div className="mb-3.5 flex flex-col items-center gap-2.5 text-center">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-[15px] font-bold text-primary-foreground">
          T
        </div>
        <h1 className="text-2xl font-bold text-foreground">TripPlanner 시작하기</h1>
        <p className="text-sm text-muted-foreground">SSO 계정으로 로그인하면 자동으로 가입돼요</p>
      </div>

      <div className="flex flex-col gap-2.5">
        <SocialLoginButton provider="google" onClick={() => {}} />
        <SocialLoginButton provider="naver" onClick={() => {}} />
        <p className="mt-1.5 text-center text-xs text-muted-foreground">
          가입 시 닉네임이 자동으로 생성돼요. 계속 진행하면 이용약관에 동의하는 것으로 간주합니다.
        </p>
      </div>
    </AuthLayout>
  ),
};
