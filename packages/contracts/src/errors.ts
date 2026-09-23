export type ApiErrorCode =
  | "INVALID_REQUEST"
  | "CATALOG_VERSION_NOT_FOUND"
  | "VALIDATION_FAILED"
  | "EVALUATION_REQUIRES_VALID_SELECTION"
  | "ALTERNATIVES_REQUIRES_VALID_SELECTION"
  | "RATE_LIMITED"
  | "INTERNAL_ERROR";

export interface ApiErrorResponse {
  error: {
    code: ApiErrorCode;
    message: string;
    request_id: string;
    retryable: boolean;
    details?: Record<string, unknown>;
  };
}
