import { Skeleton } from "@/components/shared/Skeleton";

export default function SuperadminLoading() {
  return (
    <div className="p-12">
      <Skeleton variant="rect" className="h-9 w-72" />
      <div className="mt-3">
        <Skeleton variant="text" className="w-96" />
      </div>
      <div className="mt-10">
        <Skeleton variant="row" count={6} />
      </div>
    </div>
  );
}
