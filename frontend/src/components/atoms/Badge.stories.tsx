import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Badge } from "./Badge";

const meta = {
  title: "Atoms/Badge",
  component: Badge,
  tags: ["autodocs"],
  args: { children: "휴양 · 자연" },
} satisfies Meta<typeof Badge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Secondary: Story = { args: { variant: "secondary" } };
export const Accent: Story = { args: { variant: "accent" } };
export const Outline: Story = { args: { variant: "outline", children: "읽기" } };
export const Destructive: Story = { args: { variant: "destructive", children: "삭제됨" } };
