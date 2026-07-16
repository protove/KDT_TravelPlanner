import * as React from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/atoms/Input";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export interface SearchBarProps extends React.ComponentPropsWithoutRef<"input"> {
  containerClassName?: string;
}

const SearchBar = React.forwardRef<HTMLInputElement, SearchBarProps>(
  ({ containerClassName, className, placeholder = "검색", ...props }, ref) => (
    <div className={cn("relative", containerClassName)}>
      <Icon
        icon={Search}
        size="sm"
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
      />
      <Input ref={ref} placeholder={placeholder} className={cn("pl-9", className)} {...props} />
    </div>
  )
);
SearchBar.displayName = "SearchBar";

export { SearchBar };
