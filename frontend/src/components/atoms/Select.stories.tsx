import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "./Select";

const meta = {
  title: "Atoms/Select",
  component: Select,
  tags: ["autodocs"],
} satisfies Meta<typeof Select>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => (
    <Select defaultValue="write">
      <SelectTrigger className="w-[160px]" aria-label="권한 선택">
        <SelectValue placeholder="권한 선택" />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectLabel>권한</SelectLabel>
          <SelectItem value="read">읽기</SelectItem>
          <SelectItem value="write">읽기쓰기</SelectItem>
        </SelectGroup>
      </SelectContent>
    </Select>
  ),
};

export const CompanionType: Story = {
  render: () => (
    <Select defaultValue="friends">
      <SelectTrigger className="w-[160px]" aria-label="동행 선택">
        <SelectValue placeholder="동행 선택" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="alone">혼자</SelectItem>
        <SelectItem value="friends">친구와</SelectItem>
        <SelectItem value="family">가족과</SelectItem>
        <SelectItem value="etc">기타</SelectItem>
      </SelectContent>
    </Select>
  ),
};

export const Disabled: Story = {
  render: () => (
    <Select disabled>
      <SelectTrigger className="w-[160px]" aria-label="선택 불가">
        <SelectValue placeholder="선택 불가" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="a">A</SelectItem>
      </SelectContent>
    </Select>
  ),
};
