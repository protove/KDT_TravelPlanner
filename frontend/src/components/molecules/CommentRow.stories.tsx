import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { CommentRow } from "./CommentRow";

const meta = {
  title: "Molecules/CommentRow",
  component: CommentRow,
  tags: ["autodocs"],
  args: {
    name: "이하늘",
    avatarColor: "#0369a1",
    timeLabel: "3시간 전",
    text: "경로 순서 좋네요!",
    reactionCount: 2,
    isReacted: false,
  },
  decorators: [(Story) => <div className="w-[320px]"><Story /></div>],
} satisfies Meta<typeof CommentRow>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Mine: Story = {
  args: {
    reactionCount: 5,
    isReacted: true,
    onToggleReaction: () => {},
    onEdit: async () => true,
    onDelete: () => {},
  },
};

export const Edited: Story = {
  args: { edited: true },
};
