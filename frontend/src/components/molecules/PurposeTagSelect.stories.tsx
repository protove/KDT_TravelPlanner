import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { PurposeTagSelect } from "./PurposeTagSelect";

const meta = {
  title: "Molecules/PurposeTagSelect",
  component: PurposeTagSelect,
  tags: ["autodocs"],
} satisfies Meta<typeof PurposeTagSelect>;

export default meta;
type Story = StoryObj<typeof meta>;

const OPTIONS = ["휴양 · 자연", "관광 · 명소", "미식", "액티비티/체험", "쇼핑", "기타"];

function Demo() {
  const [selected, setSelected] = React.useState(["휴양 · 자연"]);
  function toggle(option: string) {
    setSelected((prev) => (prev.includes(option) ? prev.filter((o) => o !== option) : [...prev, option]));
  }
  return <PurposeTagSelect options={OPTIONS} selected={selected} onToggle={toggle} />;
}

export const Default: Story = {
  args: { options: OPTIONS, selected: ["휴양 · 자연"], onToggle: () => {} },
  render: () => <Demo />,
};
