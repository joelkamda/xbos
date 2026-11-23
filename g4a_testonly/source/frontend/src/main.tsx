import React from "react";
import {createRoot} from "react-dom/client";
import V24IntegratedRestaurant from "./rehearsal_v3/V24IntegratedRestaurant";
const root=document.getElementById("root");
if(!root)throw new Error("TEST_ROOT_MISSING");
createRoot(root).render(<React.StrictMode><V24IntegratedRestaurant/></React.StrictMode>);
