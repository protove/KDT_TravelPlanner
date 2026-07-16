import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./Tabs";

const meta = {
  title: "Atoms/Tabs",
  component: Tabs,
  tags: ["autodocs"],
} satisfies Meta<typeof Tabs>;

export default meta;
type Story = StoryObj<typeof meta>;

export const TripListTabs: Story = {
  render: () => (
    <Tabs defaultValue="mine" className="w-96">
      <TabsList>
        <TabsTrigger value="mine">내 일정</TabsTrigger>
        <TabsTrigger value="shared">공유받은 일정</TabsTrigger>
      </TabsList>
      <TabsContent value="mine" className="text-sm text-muted-foreground">
        내가 만든 여행일정 목록이 여기에 표시됩니다.
      </TabsContent>
      <TabsContent value="shared" className="text-sm text-muted-foreground">
        초대받은 여행일정 목록이 여기에 표시됩니다.
      </TabsContent>
    </Tabs>
  ),
};
