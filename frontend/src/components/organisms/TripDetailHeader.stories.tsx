import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { TripDetailHeader } from "./TripDetailHeader";

const meta = {
  title: "Organisms/TripDetailHeader",
  component: TripDetailHeader,
  tags: ["autodocs"],
  args: {
    title: "도쿄 벚꽃 여행",
    start: new Date(2027, 3, 2),
    end: new Date(2027, 3, 5),
  },
} satisfies Meta<typeof TripDetailHeader>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
