import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { DateRangeBadge } from "./DateRangeBadge";

const meta = {
  title: "Molecules/DateRangeBadge",
  component: DateRangeBadge,
  tags: ["autodocs"],
} satisfies Meta<typeof DateRangeBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { start: new Date(2027, 3, 2), end: new Date(2027, 3, 5) },
};

export const SingleDay: Story = {
  args: { start: new Date(2027, 3, 2), end: new Date(2027, 3, 2) },
};
