import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Label } from "./Label";
import { Input } from "./Input";

const meta = {
  title: "Atoms/Label",
  component: Label,
  tags: ["autodocs"],
} satisfies Meta<typeof Label>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { children: "닉네임" } };

export const WithInput: Story = {
  render: () => (
    <div className="grid w-72 gap-1.5">
      <Label htmlFor="nickname">닉네임</Label>
      <Input id="nickname" placeholder="닉네임으로 검색" />
    </div>
  ),
};
