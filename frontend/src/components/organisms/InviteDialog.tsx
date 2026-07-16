"use client";

import * as React from "react";
import { Button } from "@/components/atoms/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/atoms/Dialog";
import { SearchBar } from "@/components/molecules/SearchBar";
import { UserChip } from "@/components/molecules/UserChip";
import { PermissionSelect, type Permission } from "@/components/molecules/PermissionSelect";

export interface InviteCandidate {
  id: string;
  name: string;
  avatarColor?: string;
  permission: Permission;
}

export interface InviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  query: string;
  onQueryChange: (value: string) => void;
  results: InviteCandidate[];
  onPermissionChange: (id: string, permission: Permission) => void;
  onInvite: (id: string) => void;
}

function InviteDialog({
  open,
  onOpenChange,
  query,
  onQueryChange,
  results,
  onPermissionChange,
  onInvite,
}: InviteDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>참여자 초대</DialogTitle>
          <DialogDescription>닉네임으로 검색해 초대하고 권한을 부여하세요.</DialogDescription>
        </DialogHeader>

        <SearchBar
          placeholder="닉네임 검색"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
        />

        <div className="flex flex-col gap-2">
          {results.map((candidate) => (
            <div key={candidate.id} className="flex items-center gap-2.5 rounded-xl bg-card p-2.5 shadow-card">
              <UserChip name={candidate.name} avatarColor={candidate.avatarColor} className="flex-1" />
              <PermissionSelect
                value={candidate.permission}
                onChange={(value) => onPermissionChange(candidate.id, value)}
              />
              <Button size="sm" onClick={() => onInvite(candidate.id)}>
                초대
              </Button>
            </div>
          ))}
          {results.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">검색 결과가 없어요.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export { InviteDialog };
