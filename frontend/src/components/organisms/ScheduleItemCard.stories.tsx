import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { ScheduleItemCard } from "./ScheduleItemCard";

const meta = {
  title: "Organisms/ScheduleItemCard",
  component: ScheduleItemCard,
  tags: ["autodocs"],
  args: { order: 1, placeName: "나리타 국제공항" },
  decorators: [(Story) => <div className="w-[360px]"><Story /></div>],
} satisfies Meta<typeof ScheduleItemCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithNote: Story = { args: { note: "도착 후 리무진버스로 이동" } };
export const NoNote: Story = {};
export const Last: Story = { args: { note: "체크인 후 자유시간", isLast: true } };
