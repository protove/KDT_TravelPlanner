import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Skeleton } from "./Skeleton";

const meta = {
  title: "Atoms/Skeleton",
  component: Skeleton,
  tags: ["autodocs"],
} satisfies Meta<typeof Skeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Text: Story = { args: { className: "h-4 w-48" } };
export const Circle: Story = { args: { className: "h-9 w-9 rounded-full" } };
export const Card: Story = { args: { className: "h-40 w-72 rounded-xl" } };
