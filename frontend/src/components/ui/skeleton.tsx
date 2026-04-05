import { cn } from "@/lib/utils";

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("skel-shimmer rounded", className)}
      {...props}
    />
  );
}

export { Skeleton };
