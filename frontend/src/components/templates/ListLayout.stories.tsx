import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { AppHeader } from "@/components/organisms/AppHeader";
import { TripList } from "@/components/organisms/TripList";
import { Button } from "@/components/atoms/Button";
import { ListLayout } from "./ListLayout";

const meta = {
  title: "Templates/ListLayout",
  component: ListLayout,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ListLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { children: null },
  render: () => (
    <ListLayout
      header={<AppHeader loggedIn userInitial="지" />}
      title={<h1 className="text-2xl font-bold text-foreground">여행일정</h1>}
      actions={<Button>새 여행 만들기</Button>}
    >
      <TripList
        trips={[
          {
            id: "1",
            title: "도쿄 벚꽃 여행",
            dates: "2027.04.02 - 04.05",
            days: 4,
            dday: 12,
            members: [{ initial: "지", color: "#3b82f6" }],
          },
          {
            id: "2",
            title: "부산 바다 여행",
            dates: "2027.06.10 - 06.12",
            days: 3,
            dday: 40,
            members: [{ initial: "유", color: "#0ea5e9" }],
          },
        ]}
      />
    </ListLayout>
  ),
};
