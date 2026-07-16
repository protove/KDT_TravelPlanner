import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { ProfileSection, type Gender } from "./ProfileSection";

const meta = {
  title: "Organisms/ProfileSection",
  component: ProfileSection,
  tags: ["autodocs"],
  decorators: [(Story) => <div className="w-[360px]"><Story /></div>],
} satisfies Meta<typeof ProfileSection>;

export default meta;
type Story = StoryObj<typeof meta>;

function Demo() {
  const [nickname, setNickname] = React.useState("김지민");
  const [gender, setGender] = React.useState<Gender>("unspecified");
  const [age, setAge] = React.useState<number | "">(28);

  return (
    <ProfileSection
      nickname={nickname}
      onNicknameChange={setNickname}
      gender={gender}
      onGenderChange={setGender}
      age={age}
      onAgeChange={(value) => setAge(value === "" ? "" : Number(value))}
      avatarColor="#3b82f6"
      onSave={() => {}}
    />
  );
}

const noopArgs = {
  nickname: "",
  onNicknameChange: () => {},
  gender: "unspecified" as Gender,
  onGenderChange: () => {},
  age: "" as number | "",
  onAgeChange: () => {},
  onSave: () => {},
};

export const Default: Story = { args: noopArgs, render: () => <Demo /> };
