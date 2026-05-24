import axios from "axios";

const baseURL = import.meta.env.VITE_NENGOK_API_BASE_URL ?? "/api/v1";

export const apiClient = axios.create({
  baseURL,
  timeout: 10_000,
});
