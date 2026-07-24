import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { SocialLoginButton } from "./SocialLoginButton";

const meta = {
  title: "Molecules/SocialLoginButton",
  component: SocialLoginButton,
  tags: ["autodocs"],
  args: { onClick: () => {} },
  render: (args) => (
    <div className="flex w-80 flex-col gap-2.5">
      <SocialLoginButton {...args} />
    </div>
  ),
} satisfies Meta<typeof SocialLoginButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Google: Story = { args: { provider: "google" } };
export const Naver: Story = { args: { provider: "naver" } };

export const Stacked: Story = {
  args: { provider: "google" },
  render: () => (
    <div className="flex w-80 flex-col gap-2.5">
      <SocialLoginButton provider="google" onClick={() => {}} />
      <SocialLoginButton provider="naver" onClick={() => {}} />
    </div>
  ),
};
