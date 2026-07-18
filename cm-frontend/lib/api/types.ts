export type Pagination = {
  total: number;
  offset: number;
  limit: number;
};

export type ListResponse<T> = {
  items: T[];
  pagination: Pagination;
};

export type ApiErrorBody = {
  code: string;
  message: string;
  details: unknown;
  request_id: string;
};
