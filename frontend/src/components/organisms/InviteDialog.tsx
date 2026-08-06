"use client";

import * as React from "react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/atoms/Dialog";
import { PermissionSelect, type Permission } from "@/components/molecules/PermissionSelect";

export interface InviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nickname: string;
  onNicknameChange: (value: string) => void;
  permission: Permission;
  onPermissionChange: (value: Permission) => void;
  onInvite: () => void;
  /** 정확한 닉네임을 찾지 못했을 때 등, 초대 실패 사유를 보여준다. */
  error?: string | null;
}

function InviteDialog({
  open,
  onOpenChange,
  nickname,
  onNicknameChange,
  permission,
  onPermissionChange,
  onInvite,
  error,
}: InviteDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>참여자 초대</DialogTitle>
          <DialogDescription>정확한 닉네임을 입력해 초대하고 권한을 부여하세요.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <Input
            placeholder="닉네임 입력"
            value={nickname}
            onChange={(e) => onNicknameChange(e.target.value)}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex items-center justify-between gap-2">
            <PermissionSelect value={permission} onChange={onPermissionChange} />
            <Button size="sm" disabled={!nickname.trim()} onClick={onInvite}>
              초대
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export { InviteDialog };
