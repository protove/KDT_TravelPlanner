import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { NotificationList } from "./NotificationList";

const meta = {
  title: "Organisms/NotificationList",
  component: NotificationList,
  tags: ["autodocs"],
  decorators: [(Story) => <div className="w-[360px]"><Story /></div>],
} satisfies Meta<typeof NotificationList>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    notifications: [
      { id: "1", inviterName: "박수아", tripTitle: "도쿄 벚꽃 여행" },
      { id: "2", inviterName: "이하늘", tripTitle: "부산 바다 여행" },
    ],
    onAccept: () => {},
    onReject: () => {},
  },
};

export const Empty: Story = { args: { notifications: [], onAccept: () => {}, onReject: () => {} } };
