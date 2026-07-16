import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { UserChip } from "./UserChip";

const meta = {
  title: "Molecules/UserChip",
  component: UserChip,
  tags: ["autodocs"],
  args: { name: "박유진" },
} satisfies Meta<typeof UserChip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { avatarColor: "#0ea5e9" } };
export const WithImage: Story = { args: { avatarSrc: "https://github.com/shadcn.png" } };

export const Group: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <UserChip name="김지민" avatarColor="#3b82f6" />
      <UserChip name="이하늘" avatarColor="#0ea5e9" />
      <UserChip name="박수아" avatarColor="#9747ff" />
    </div>
  ),
};
