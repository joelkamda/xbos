import {useState,type FormEvent} from "react";
import "./V3Rehearsal.css";
import "./V24OperatorAccessibility.css";
/** V24 native browser -> FastAPI -> PostgreSQL; all principals and effects synthetic TEST only. */
type Role="merchant"|"reviewer"|"cashier"|"closer";
type ApiResult=Record<string,unknown>;
const roleNames={
 en:{merchant:"Merchant",reviewer:"Reviewer",cashier:"Cashier",closer:"Period closer"},
 fr:{merchant:"Commerçant",reviewer:"Réviseur",cashier:"Caissier",closer:"Responsable clôture"}
} as const;
const translations={
 en:{
  title:"WND V24 Restaurant Pack — integrated TEST",grade:"Native PostgreSQL TEST · no actual payment, printing or PC5",
  signIn:"Sign in with synthetic TEST role",role:"Role",password:"TEST password",login:"Sign in",logout:"Revoke session",
  product:"Merchant products",name:"Product name",draft:"Create draft",edit:"Set Main / VIP / Bar prices",
  request:"Request review",publish:"Publish to native catalog",hist:"Read product history",
  order:"Restaurant sale",sale:"Save native POS order",kitchen:"Mark kitchen READY",cash:"Record TEST cash",
  pending:"Record provider-pending tender",allocation:"Read unpaid balance",receipt:"80mm receipt preview",
  discount:"Apply TEST discount",pendingOrders:"List pending orders",resume:"Resume existing order",
  costRule:"Set drink COGS policy",costRead:"Read native COGS",forward:"Forward Finance amendment",
  stock:"Stock and COGS",count:"Create stock count draft",saveCount:"Save physical TEST count",
  approveCount:"Review and reconcile stock",movements:"Read native movements",
  finance:"Finance and month close",period:"Open TEST period",entry:"Write TEST Finance draft",
  cancel:"Compensating cancellation",prepare:"Prepare month close",review:"Independent review",
  close:"Close TEST period",reports:"Reports",page:"Read indexed report page",
  export:"Export complete TEST report",lang:"Français",scope:"TEST only · tenant 920002 · no customer data",
  productCategory:"Category",productFamily:"Department",productUnit:"Unit",
  mainPrice:"Main price (XAF)",vipPrice:"VIP price (XAF)",barPrice:"Bar price (XAF)",
  openingStock:"Stock (blank = unknown)",reportKind:"Report kind",reportChannel:"Payment channel",
  reportLimit:"Page size",reportAsOf:"As-of timestamp",reportNext:"Next page",
  reportAll:"All",daily:"Daily and shift report",dailyDay:"Business date",
  dailyShift:"Shift",dailyRead:"Read native daily report",stockAt:"As-of timestamp",
  stockHistory:"Read as-of stock and discrepancy",
  dailyExport:"Download TEST daily statement",shiftCount:"Cashier cash count (XAF)",
  shiftRecon:"Save TEST shift reconciliation draft",ledgerBrowse:"Browse Finance drafts and source events",
  debtor:"Debtor / Accounts receivable",debtorName:"Debtor display name",
  debtorCreate:"Create TEST debtor",debtorSearch:"Search TEST debtors",
  debtorLink:"Link this unpaid order to debtor",debtorDetail:"Read linked A/R",
  debtorAmount:"TEST installment amount",debtorChannel:"Installment channel",
  debtorPay:"Record TEST installment",debtorStatement:"Debtor statement",debtorAudit:"A/R audit",
  handoff:"Cashier shift handoff",handoffOpening:"Opening cash (XAF)",
  handoffActual:"Physically counted cash (XAF)",handoffPreview:"Preview signed cash variance",
  reprintRequest:"Request duplicate TEST receipt",reprintReview:"Approve duplicate preview",
  reprintPreview:"View approved duplicate preview",priceVersions:"Zone price revisions",
  status:"Execution status",username:"Actor",ready:"Ready",
  none:"None",session:"Limited synthetic TEST session",
  success:"TEST action completed",denied:"Action denied",
  revocationError:"Session revocation failed; TEST session remains active",
  securityNotice:"Server-side permissions remain authoritative"
 },
 fr:{
  title:"WND V24 — Pack Restaurant TEST intégré",grade:"TEST PostgreSQL natif · aucun paiement, impression ni PC5 réel",
  signIn:"Connexion avec rôle TEST synthétique",role:"Rôle",password:"Mot de passe TEST",login:"Se connecter",logout:"Révoquer la session",
  product:"Produits du commerçant",name:"Nom du produit",draft:"Créer le brouillon",edit:"Saisir prix Main / VIP / Bar",
  request:"Soumettre pour validation",publish:"Publier dans le catalogue",hist:"Consulter l'historique",
  order:"Vente au restaurant",sale:"Enregistrer la commande TEST",kitchen:"Marquer prêt en cuisine",
  cash:"Encaisser espèces TEST",pending:"Enregistrer paiement fournisseur en attente",allocation:"Lire le solde impayé",
  discount:"Appliquer remise TEST",pendingOrders:"Lister commandes en attente",resume:"Reprendre commande",
  costRule:"Définir coût des boissons",costRead:"Lire coût de revient",forward:"Amendement Finance ultérieur",
  receipt:"Aperçu ticket 80mm",stock:"Stock et coût de revient",count:"Créer le comptage",saveCount:"Enregistrer le comptage",
  approveCount:"Approuver l'ajustement",movements:"Lire les mouvements",
  finance:"Finance et clôture",period:"Ouvrir période TEST",entry:"Saisir brouillon Finance TEST",
  cancel:"Annulation compensatoire",prepare:"Préparer clôture",review:"Révision indépendante",
  close:"Clôturer période TEST",reports:"Rapports",page:"Lire page du rapport",
  export:"Exporter rapport TEST complet",lang:"English",scope:"TEST uniquement · locataire 920002 · aucune donnée client",
  productCategory:"Catégorie",productFamily:"Département",productUnit:"Unité",
  mainPrice:"Prix Main (XAF)",vipPrice:"Prix VIP (XAF)",barPrice:"Prix Bar (XAF)",
  openingStock:"Stock (vide = inconnu)",reportKind:"Type de rapport",reportChannel:"Canal de paiement",
  reportLimit:"Lignes par page",reportAsOf:"État à la date",reportNext:"Page suivante",
  reportAll:"Tous",daily:"Rapport journalier et par équipe",dailyDay:"Date commerciale",
  dailyShift:"Service",dailyRead:"Consulter le rapport journalier",stockAt:"Date du stock",
  stockHistory:"Stock à la date et écart",
  dailyExport:"Télécharger le rapport journalier TEST",shiftCount:"Comptage espèces du caissier (XAF)",
  shiftRecon:"Enregistrer rapprochement TEST du service",ledgerBrowse:"Consulter brouillons et événements Finance",
  debtor:"Débiteur / Comptes clients",debtorName:"Nom du débiteur",
  debtorCreate:"Créer débiteur TEST",debtorSearch:"Rechercher débiteurs TEST",
  debtorLink:"Lier facture impayée au débiteur",debtorDetail:"Consulter créance liée",
  debtorAmount:"Montant acompte TEST",debtorChannel:"Canal de l'acompte",
  debtorPay:"Enregistrer acompte TEST",debtorStatement:"Relevé débiteur",debtorAudit:"Journal des créances",
  handoff:"Passation de service caisse",handoffOpening:"Espèces d'ouverture (XAF)",
  handoffActual:"Espèces réellement comptées (XAF)",handoffPreview:"Aperçu de l'écart de caisse",
  reprintRequest:"Demander duplicata reçu TEST",reprintReview:"Approuver aperçu du duplicata",
  reprintPreview:"Afficher aperçu duplicata approuvé",priceVersions:"Révisions prix par zone",
  status:"État d'exécution",username:"Acteur",ready:"Prêt",
  none:"Aucun",session:"Session TEST synthétique limitée",
  success:"Action TEST terminée",denied:"Action refusée",
  revocationError:"Échec de révocation ; la session TEST reste active",
  securityNotice:"Les permissions du serveur restent seules décisives"
 }
};
export default function V24IntegratedRestaurant(){
 const [locale,setLocale]=useState<"en"|"fr">("en");
 const T=translations[locale];
 const [chosenRole,setChosenRole]=useState<Role>("merchant");
 const [password,setPassword]=useState("");
 const [token,setToken]=useState("");
 const [loggedRole,setLoggedRole]=useState<Role|null>(null);
 const [name,setName]=useState("V24 Synthetic Guest Juice");
 const [sku,setSku]=useState("");
 const [revision,setRevision]=useState(0);
 const [priceRevisions,setPriceRevisions]=useState<[number,number,number]>([1,1,1]);
 const [reprintId,setReprintId]=useState("");
 const [reprintRevision,setReprintRevision]=useState(0);
 const [category,setCategory]=useState("MOCK DRINK");
 const [family,setFamily]=useState<"bar"|"kitchen"|"other">("bar");
 const [unit,setUnit]=useState("BOTTLE");
 const [mainXaf,setMainXaf]=useState("1700");
 const [vipXaf,setVipXaf]=useState("2300");
 const [barXaf,setBarXaf]=useState("1900");
 const [stock,setStock]=useState("20");
 const [reportKind,setReportKind]=useState("");
 const [reportChannel,setReportChannel]=useState("");
 const [reportLimit,setReportLimit]=useState("25");
 const [reportAsOf,setReportAsOf]=useState("2026-11-22T23:00:00+01:00");
 const [reportCursor,setReportCursor]=useState<string|null>(null);
 const [dailyDay,setDailyDay]=useState("2026-11-22");
 const [dailyShift,setDailyShift]=useState<"ALL"|"DAY"|"NIGHT">("ALL");
 const [stockAsOf,setStockAsOf]=useState("2026-11-22T23:00:00+01:00");
 const [shiftCashCount,setShiftCashCount]=useState("0");
 const [shiftOpening,setShiftOpening]=useState("0");
 const [handoffCount,setHandoffCount]=useState("0");
 const [debtorName,setDebtorName]=useState("Synthetic R6 Guest");
 const [debtorId,setDebtorId]=useState("");
 const [obligationId,setObligationId]=useState("");
 const [obligationRevision,setObligationRevision]=useState(0);
 const [collectionAmount,setCollectionAmount]=useState("100");
 const [collectionChannel,setCollectionChannel]=useState("CASH");
 const [orderId,setOrderId]=useState("");
 const [orderTotal,setOrderTotal]=useState(0);
 const [discountXaf,setDiscountXaf]=useState(0);
 const [ticketId,setTicketId]=useState("");
 const [countId,setCountId]=useState("");
 const [countRevision,setCountRevision]=useState(0);
 const [financeId,setFinanceId]=useState("");
 const [periodRevision,setPeriodRevision]=useState(0);
 const [notice,setNotice]=useState("");
 const [noticeError,setNoticeError]=useState(false);
 const [details,setDetails]=useState("");
 const [busy,setBusy]=useState(false);
 const reportQuery=(cursor:string|null=null)=>{
  const q=new URLSearchParams({as_of:reportAsOf,limit:reportLimit});
  if(reportKind)q.set("kind",reportKind);
  if(reportChannel)q.set("channel",reportChannel);
  if(cursor)q.set("cursor",cursor);
  return q.toString();
 };
 const reportPage=async(cursor:string|null=null)=>{
   const result=await call("/v24/reports/page?"+reportQuery(cursor));
   setReportCursor(typeof result.nextCursor==="string"?result.nextCursor:null);
   return result;
 };
 const positiveInt=(v:string,name:string)=>{
   const n=Number(v);
   if(!Number.isSafeInteger(n)||n<0)throw new Error(name+": whole XAF required");
   return n;
 };
 async function call(path:string,method="GET",body?:object):Promise<ApiResult>{
  const response=await fetch("/api/v3"+path,{
   method,headers:{"Content-Type":"application/json",...(token?{"X-Rehearsal-Token":token}:{})},
   body:body===undefined?undefined:JSON.stringify(body),credentials:"omit",cache:"no-store"});
  const data=(await response.json().catch(()=>({detail:"NON_JSON_RESPONSE"}))) as ApiResult;
  if(!response.ok)throw new Error(String(data.detail||response.status));
  return data;
 }
 async function action(label:string,work:()=>Promise<ApiResult>){
  setBusy(true);try{const result=await work();setNoticeError(false);setNotice(label+" — "+T.success);setDetails(JSON.stringify(Array.isArray(result.rows)?{...result,rows:result.rows.slice(0,2),returnedRows:result.rows.length,nextCursorPresent:Boolean(result.nextCursor)}:result,null,2).slice(0,5000))}
  catch(e){setNoticeError(true);setNotice(label+" — "+T.denied+": "+String(e));setDetails("")}
  finally{setBusy(false)}
 }
 async function login(e:FormEvent){
  e.preventDefault();setBusy(true);
  try{
   const response=await fetch("/api/v3/session",{method:"POST",headers:{"Content-Type":"application/json"},
     body:JSON.stringify({username:chosenRole,password}),cache:"no-store",credentials:"omit"});
   if(!response.ok)throw new Error("TEST_LOGIN_DENIED");
   const result=(await response.json()) as {token:string;pc5:boolean};
   if(result.pc5!==false)throw new Error("PC5_UNEXPECTED");
   if(typeof result.token!=="string"||result.token.length<12)
     throw new Error("INVALID_TEST_SESSION_TOKEN");
   setToken(result.token);setLoggedRole(chosenRole);setPassword("");setNoticeError(false);setNotice(T.session+": "+roleNames[locale][chosenRole]);
  }catch(e){setNoticeError(true);setNotice(T.denied+": "+String(e))}finally{setBusy(false)}
 }
 async function logout(){
  if(!token)return;
  setBusy(true);
  try{
   await call("/session/revoke","POST");
   setToken("");setLoggedRole(null);setPassword("");
   setNoticeError(false);setNotice(T.logout+" — "+T.success);
   setDetails("");
  }catch{
   // Do not report server revocation or clear the token when it was denied.
   setNoticeError(true);setNotice(T.revocationError);
  }finally{setBusy(false)}
 }
 function task(label:string,handler:()=>Promise<ApiResult>,disabled=false){
  return <button type="button" disabled={busy||!token||disabled} aria-disabled={busy||!token||disabled} aria-busy={busy}
    style={{padding:"9px 12px",border:"1px solid #789",borderRadius:8,margin:4}}
    onClick={()=>void action(label,handler)}>{label}</button>;
 }
 return <main className="v24-accessible" lang={locale} style={{maxWidth:1050,margin:"auto",padding:24,fontFamily:"system-ui"}}>
  <a href="#v24-workflows" className="v24-skip-link">{locale==="en"?"Skip to merchant workflows":"Passer aux op?rations du commer?ant"}</a>
  <header><p style={{fontWeight:700,color:"#136c58"}}>XAFPAY · WND · V24</p>
   <h1>{T.title}</h1><p>{T.grade}</p><p>{T.scope}</p><p className="v24-authz-notice">{T.securityNotice}</p>
   <button type="button" aria-label={locale==="en"?"Switch to French":"Passer en anglais"} onClick={()=>setLocale(locale==="en"?"fr":"en")}>
    {T.lang}</button></header>
  <form onSubmit={login} aria-label={T.signIn} style={{padding:16,border:"1px solid #bbb",marginTop:12}}>
   <h2>{T.signIn}</h2>
   <label htmlFor="v24-role">{T.role}</label>
   <select id="v24-role" value={chosenRole} onChange={e=>setChosenRole(e.target.value as Role)}
    style={{margin:8}}>
    {(["merchant","reviewer","cashier","closer"] as Role[]).map(role=><option key={role} value={role}>{({en:{merchant:"Merchant",reviewer:"Reviewer",cashier:"Cashier",closer:"Period closer"},fr:{merchant:"Commerçant",reviewer:"Réviseur",cashier:"Caissier",closer:"Responsable clôture"}} as const)[locale][role]}</option>)}
   </select>
   <label htmlFor="v24-password">{T.password}</label>
   <input id="v24-password" type="password" value={password} onChange={e=>setPassword(e.target.value)}
    required aria-label={T.password} style={{margin:8,border:"1px solid #aaa"}}/>
   <button type="submit" disabled={busy}>{T.login}</button>
   {token&&<button type="button" onClick={()=>void logout()}>{T.logout}</button>}
   <p role="status" data-testid="v24-active-role">{T.username}: {loggedRole?roleNames[locale][loggedRole]:T.none} · {T.session}</p>
  </form>
  <nav className="v24-workflow-nav" aria-label={locale==="en"?"Jump to restaurant workflow":"Accéder aux opérations du restaurant"}>
     {([
       ["v24-products",T.product],["v24-sale",T.order],["v24-stock",T.stock],
       ["v24-finance",T.finance],["v24-ar",T.debtor],["v24-daily",T.daily],["v24-reports",T.reports]
     ] as const).map(([id,label])=><a href={"#"+id} key={id}>{label}</a>)}
   </nav>
  <div id="v24-workflows" tabIndex={-1} style={{display:"grid",gap:16,marginTop:18}}>
   <section id="v24-products" tabIndex={-1} aria-labelledby="product-title" style={{padding:15,border:"1px solid #bbb"}}>
    <h2 id="product-title">{T.product}</h2>
    <label htmlFor="v24-name">{T.name}</label>
    <input id="v24-name" value={name} onChange={e=>setName(e.target.value)}
      style={{margin:8,border:"1px solid #aaa"}}/>
    {task(T.draft,async()=>{const r=await call("/v24/products/draft","POST",{name});
       setSku(String(r.sku));setRevision(Number(r.revision));setPriceRevisions([1,1,1]);return r})}
    <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:8}}>
     <label>{T.productCategory}<input aria-label={T.productCategory} value={category}
       onChange={e=>setCategory(e.target.value)} required/></label>
     <label>{T.productFamily}<select aria-label={T.productFamily} value={family}
       onChange={e=>setFamily(e.target.value as "bar"|"kitchen"|"other")}>
       <option value="bar">Bar</option><option value="kitchen">Kitchen / Cuisine</option>
       <option value="other">Other / Autre</option></select></label>
     <label>{T.productUnit}<input aria-label={T.productUnit} value={unit}
       onChange={e=>setUnit(e.target.value)} required/></label>
     <label>{T.mainPrice}<input aria-label={T.mainPrice} type="number" min="0" step="1" value={mainXaf}
       onChange={e=>setMainXaf(e.target.value)}/></label>
     <label>{T.vipPrice}<input aria-label={T.vipPrice} type="number" min="0" step="1" value={vipXaf}
       onChange={e=>setVipXaf(e.target.value)}/></label>
     <label>{T.barPrice}<input aria-label={T.barPrice} type="number" min="0" step="1" value={barXaf}
       onChange={e=>setBarXaf(e.target.value)}/></label>
     <label>{T.openingStock}<input aria-label={T.openingStock} type="number" min="0" step="1"
       value={stock} onChange={e=>setStock(e.target.value)}/></label>
    </div>
    {task(T.edit,async()=>{const r=await call("/v24/products/"+sku,"PUT",
       {revision,name,category,family,unit,
        main_xaf:positiveInt(mainXaf,"MAIN"),vip_xaf:positiveInt(vipXaf,"VIP"),
        bar_xaf:positiveInt(barXaf,"BAR"),
        stock_qty:stock.trim()===""?null:positiveInt(stock,"STOCK")});
        setRevision(Number(r.revision));
        if(Array.isArray(r.priceRevisions) && r.priceRevisions.length===3)
          setPriceRevisions(r.priceRevisions.map(Number) as [number,number,number]);
        return r},!sku)}
    {task(T.request,async()=>{const r=await call("/v24/products/"+sku+"/review","POST",{revision});
        setRevision(Number(r.revision));
        if(Array.isArray(r.priceRevisions) && r.priceRevisions.length===3)
          setPriceRevisions(r.priceRevisions.map(Number) as [number,number,number]);
        return r},!sku)}
    {task(T.publish,async()=>{const r=await call("/v24/products/"+sku+"/publish","POST",{revision,price_revisions:priceRevisions});
        setRevision(Number(r.revision));return r},!sku)}
    <p data-testid="v24-price-revisions">{T.priceVersions}: {priceRevisions.join(" / ")}</p>
    {task(T.hist,()=>call("/v24/products/"+sku+"/history"),!sku)}
    <p data-testid="v24-sku">SKU: {sku||"NONE"} · Revision {revision}</p>
   </section>
   <section id="v24-sale" tabIndex={-1} aria-labelledby="order-title" style={{padding:15,border:"1px solid #bbb"}}>
    <h2 id="order-title">{T.order}</h2>
    {task(T.sale,async()=>{const r=await call("/orders","POST",{
       idempotency_key:"v24-ui-"+Date.now(),zone:"MAIN",
       lines:[{sku,quantity:1},{sku:"TEST-FOOD-01",quantity:1}]});
       setOrderId(String(r.orderId));setOrderTotal(Number(r.totalXaf));setDiscountXaf(0);
       const kitchen=await call("/kitchen");
       const tickets=(kitchen.tickets||[]) as Array<{id:string;order_id:string}>;
       setTicketId(tickets.find(t=>t.order_id===r.orderId)?.id||"");
       return r},!sku)}
    {task(T.kitchen,()=>call("/kitchen/"+ticketId+"/ready","POST"),!ticketId)}
    {task(T.discount,async()=>{const r=await call("/v24/orders/"+orderId+"/discount","POST",
       {amount_xaf:400,reason:"Synthetic promotional adjustment"});setDiscountXaf(400);return r},!orderId)}
    {task(T.pendingOrders,()=>call("/v24/orders/pending"))}
    {task(T.resume,()=>call("/v24/orders/"+orderId+"/resume","POST"),!orderId)}
    {task(T.cash,()=>call("/v24/orders/"+orderId+"/tender","POST",
       {idem:"ui-cash-"+orderId,channel:"CASH",amount_xaf:2000,state:"CASH_RECEIVED_TEST"}),!orderId)}
    {task(T.pending,()=>call("/v24/orders/"+orderId+"/tender","POST",
       {idem:"ui-mtn-"+orderId,channel:"MTN",amount_xaf:orderTotal-discountXaf-2000,state:"PROVIDER_PENDING_TEST"}),!orderId)}
    {task(T.allocation,()=>call("/v24/orders/"+orderId+"/allocation"),!orderId)}
    {task(T.receipt,()=>call("/v24/orders/"+orderId+"/receipt-preview"),!orderId)}
    {task(T.reprintRequest,async()=>{
       const r=await call("/v24/w/receipt-custody/orders/"+orderId+"/request","POST",
          {idem:"r7-ui-duplicate-"+orderId,reason:"Synthetic TEST duplicate receipt request"});
       setReprintId(String(r.requestId));setReprintRevision(Number(r.revision));return r
    },!orderId)}
    {task(T.reprintReview,async()=>{
       const r=await call("/v24/w/receipt-custody/requests/"+reprintId+"/review","POST",
          {revision:reprintRevision,decision:"APPROVE_PREVIEW_TEST",
           reason:"Synthetic independent duplicate preview approval"});
       setReprintRevision(Number(r.revision));return r
    },!reprintId)}
    {task(T.reprintPreview,()=>call("/v24/w/receipt-custody/requests/"+reprintId+"/preview"),!reprintId)}
    <p data-testid="v24-order-id">Order: {orderId||"NONE"} · {orderTotal} XAF</p>
   </section>
   <section id="v24-stock" tabIndex={-1} aria-labelledby="stock-title" style={{padding:15,border:"1px solid #bbb"}}>
    <h2 id="stock-title">{T.stock}</h2>
    {task(T.count,async()=>{const r=await call("/v24/stock/counts","POST",{sku});
       setCountId(String(r.draftId));setCountRevision(Number(r.revision));return r},!sku)}
    {task(T.saveCount,async()=>{const r=await call("/v24/stock/counts/"+countId,"PUT",
       {revision:countRevision,count_qty:18});setCountRevision(Number(r.revision));return r},!countId)}
    {task(T.approveCount,()=>call("/v24/stock/counts/"+countId+"/approve","POST",
       {revision:countRevision}),!countId)}
    {task(T.movements,()=>call("/v24/stock/"+sku+"/movements"),!sku)}
    {task(T.costRule,()=>call("/v24/stock/"+sku+"/cost-policy","POST",
       {policy:"DRINK_AUTO_TEST",unit_cost_xaf:650}),!sku)}
    {task(T.costRead,()=>call("/v24/stock/"+sku+"/cogs"),!sku)}
    <label>{T.stockAt}<input aria-label={T.stockAt} value={stockAsOf}
      onChange={e=>setStockAsOf(e.target.value)}/></label>
    {task(T.stockHistory,()=>call("/v24/r4/stock-asof?sku="+encodeURIComponent(sku)+
       "&at="+encodeURIComponent(stockAsOf)),!sku)}
   </section>
   <section id="v24-finance" tabIndex={-1} aria-labelledby="finance-title" style={{padding:15,border:"1px solid #bbb"}}>
    <h2 id="finance-title">{T.finance}</h2>
    {task(T.period,async()=>{const r=await call("/v24/finance/periods","POST",
       {period:"2026-06",opening_cash_xaf:1000});setPeriodRevision(Number(r.revision));return r})}
    {task(T.entry,async()=>{const r=await call("/v24/finance/entry","POST",
       {period:"2026-06",amount_xaf:700,channel:"CASH",kind:"INCOME_TEST",
        idem:"v24-ui-finance-"+Date.now(),note:"UI test-only entry",
        effective_at:"2026-06-22T12:00:00+01:00"});setFinanceId(String(r.ref));return r})}
    {task(T.cancel,()=>call("/v24/finance/"+financeId+"/cancel","POST",
       {period:"2026-06",reason:"UI test cancellation"}),!financeId)}
    {task(T.prepare,async()=>{const r=await call("/v24/finance/periods/2026-06/prepare","POST");
       setPeriodRevision(Number(r.revision));return r})}
    {task(T.review,async()=>{const r=await call("/v24/finance/periods/2026-06/review","POST",
       {revision:periodRevision});setPeriodRevision(Number(r.revision));return r})}
    {task(T.close,()=>call("/v24/finance/periods/2026-06/close","POST",
       {revision:periodRevision}))}
    {task(T.forward,()=>call("/v24/finance/periods/2026-06/forward-amendment","POST",
       {target_period:"2026-07",amount_xaf:-100,channel:"CASH",
        idem:"v24-ui-forward-"+Date.now(),note:"Synthetic forward correction",
        effective_at:"2026-07-22T12:00:00+01:00"}))}
   </section>
   <section id="v24-ar" tabIndex={-1} aria-labelledby="ar-title" style={{padding:15,border:"1px solid #bbb"}}>
    <h2 id="ar-title">{T.debtor}</h2>
    <label>{T.debtorName}<input aria-label={T.debtorName} value={debtorName}
      onChange={e=>setDebtorName(e.target.value)}/></label>
    {task(T.debtorCreate,async()=>{
      const r=await call("/v24/sof/ar/debtors","POST",{display_name:debtorName});
      setDebtorId(String(r.debtorId));return r})}
    {task(T.debtorSearch,()=>call("/v24/sof/ar/debtors?q="+encodeURIComponent(debtorName)))}
    {task(T.debtorLink,async()=>{
      const r=await call("/v24/sof/ar/obligations","POST",
       {debtor_id:debtorId,order_id:orderId});
      setObligationId(String(r.obligationId));setObligationRevision(Number(r.revision));return r
    },!debtorId||!orderId)}
    {task(T.debtorDetail,async()=>{
      const r=await call("/v24/sof/ar/obligations/"+obligationId);
      setObligationRevision(Number(r.revision));return r},!obligationId)}
    <label>{T.debtorAmount}<input type="number" min="1" aria-label={T.debtorAmount}
       value={collectionAmount} onChange={e=>setCollectionAmount(e.target.value)}/></label>
    <label>{T.debtorChannel}<select aria-label={T.debtorChannel}
        value={collectionChannel} onChange={e=>setCollectionChannel(e.target.value)}>
       {["CASH","MTN","ORANGE","BANK"].map(x=><option key={x} value={x}>{x}</option>)}
    </select></label>
    {task(T.debtorPay,async()=>{
      const r=await call("/v24/sof/ar/obligations/"+obligationId+"/collections","POST",
       {idem:"r6-ui-"+Date.now(),amount_xaf:positiveInt(collectionAmount,"AR"),
        channel:collectionChannel,expected_revision:obligationRevision});
      setObligationRevision(Number(r.obligationRevision));return r},!obligationId)}
    {task(T.debtorStatement,()=>call("/v24/sof/ar/debtors/"+debtorId+"/statement"),!debtorId)}
    {task(T.debtorAudit,()=>call("/v24/sof/ar/audit"))}
    <p data-testid="v24-ar-ids">Debtor: {debtorId||"NONE"} · Obligation: {obligationId||"NONE"}</p>
   </section>
   <section id="v24-daily" tabIndex={-1} aria-labelledby="daily-title" style={{padding:15,border:"1px solid #bbb"}}>
    <h2 id="daily-title">{T.daily}</h2>
    <label>{T.dailyDay}<input aria-label={T.dailyDay} type="date" value={dailyDay}
      onChange={e=>setDailyDay(e.target.value)}/></label>
    <label>{T.dailyShift}<select aria-label={T.dailyShift} value={dailyShift}
      onChange={e=>setDailyShift(e.target.value as "ALL"|"DAY"|"NIGHT")}>
       <option value="ALL">24h / 24h</option><option value="DAY">Day / Jour</option>
       <option value="NIGHT">Night / Nuit</option>
      </select></label>
    {task(T.dailyRead,()=>call("/v24/r4/daily?day="+encodeURIComponent(dailyDay)+
      "&shift="+encodeURIComponent(dailyShift)))}
    {task(T.dailyExport,async()=>{
      const q=new URLSearchParams({day:dailyDay,shift:dailyShift});
      const response=await fetch("/api/v3/v24/r4/daily/export?"+q.toString(),{
       headers:{"X-Rehearsal-Token":token},credentials:"omit",cache:"no-store"});
      if(!response.ok)throw new Error("DAILY_STATEMENT_EXPORT_DENIED");
      const data=await response.text();
      const url=URL.createObjectURL(new Blob([data],{type:"text/csv;charset=utf-8"}));
      const a=document.createElement("a");a.href=url;a.download="WND-V3-TEST-daily-shift.csv";
      a.click();URL.revokeObjectURL(url);
      return {downloaded:true,bytes:data.length,officialLedger:false};
    })}
    <label>{T.shiftCount}<input aria-label={T.shiftCount} type="number" min="0" step="1"
       value={shiftCashCount} onChange={e=>setShiftCashCount(e.target.value)}/></label>
    {task(T.shiftRecon,()=>call("/finance-b/reconciliation/draft","POST",
      {tenant_id:920002,branch_id:1,business_date:dailyDay,
       shift:dailyShift,cashier_count_xaf:positiveInt(shiftCashCount,"CASH")}),dailyShift==="ALL")}
    {task(T.ledgerBrowse,()=>call("/finance-b/entries?as_of="+encodeURIComponent(reportAsOf)+"&limit=50"))}
    <h3>{T.handoff}</h3>
    <label>{T.handoffOpening}<input type="number" min="0" aria-label={T.handoffOpening}
      value={shiftOpening} onChange={e=>setShiftOpening(e.target.value)}/></label>
    <label>{T.handoffActual}<input type="number" min="0" aria-label={T.handoffActual}
      value={handoffCount} onChange={e=>setHandoffCount(e.target.value)}/></label>
    {task(T.handoffPreview,()=>call("/v24/w/shift-handoff/preview","POST",
      {business_day:dailyDay,shift:dailyShift,
       opening_cash_xaf:positiveInt(shiftOpening,"OPENING"),
       physically_counted_cash_xaf:positiveInt(handoffCount,"ACTUAL")}),dailyShift==="ALL")}
   </section>
   <section id="v24-reports" tabIndex={-1} aria-labelledby="reports-title" style={{padding:15,border:"1px solid #bbb"}}>
    <h2 id="reports-title">{T.reports}</h2>
    <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(170px,1fr))",gap:8}}>
     <label>{T.reportAsOf}<input aria-label={T.reportAsOf} value={reportAsOf}
       onChange={e=>{setReportAsOf(e.target.value);setReportCursor(null)}}/></label>
     <label>{T.reportKind}<select aria-label={T.reportKind} value={reportKind}
       onChange={e=>{setReportKind(e.target.value);setReportCursor(null)}}>
       <option value="">{T.reportAll}</option>
       <option value="INCOME_TEST">Income / Recettes</option>
       <option value="EXPENSE_TEST">Expense / Dépenses</option>
       <option value="CANCEL_TEST">Cancellation / Annulation</option>
       <option value="FORWARD_AMENDMENT_TEST">Forward amendment</option>
      </select></label>
     <label>{T.reportChannel}<select aria-label={T.reportChannel} value={reportChannel}
       onChange={e=>{setReportChannel(e.target.value);setReportCursor(null)}}>
       <option value="">{T.reportAll}</option>
       {["CASH","MTN","ORANGE","BANK"].map(c=><option key={c} value={c}>{c}</option>)}
      </select></label>
     <label>{T.reportLimit}<input aria-label={T.reportLimit} type="number" min="1" max="500"
        value={reportLimit} onChange={e=>{setReportLimit(e.target.value);setReportCursor(null)}}/></label>
    </div>
    {task(T.page,()=>reportPage())}
    {task(T.reportNext,()=>reportPage(reportCursor),!reportCursor)}
    {task(T.export,async()=>{const res=await fetch(
       "/api/v3/v24/reports/export-test?"+reportQuery().replace(/(?:^|&)limit=[^&]*/,""),
       {headers:{"X-Rehearsal-Token":token},credentials:"omit"});
       if(!res.ok)throw new Error("TEST_REPORT_EXPORT_DENIED");
       const csv=await res.text();
       const blob=new Blob([csv],{type:"text/csv;charset=utf-8"});
       const url=URL.createObjectURL(blob);
       const link=document.createElement("a");
       link.href=url;link.download="WND-V24-TEST-report.csv";link.click();
       URL.revokeObjectURL(url);
       return {rows:res.headers.get("X-Test-Row-Count"),size:csv.length,
               syntheticOnly:true}})}
   </section>
  </div>
  <section aria-live="polite" aria-labelledby="status-title" style={{marginTop:20}}>
   <h2 id="status-title">{T.status}</h2>
   <p data-testid="v24-status" role={noticeError?"alert":"status"} aria-atomic="true">{notice||T.ready}</p>
   <pre data-testid="v24-response" style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",
       background:"#f4f5f5",color:"#222",padding:12}}>{details}</pre>
  </section>
  <footer><p>V24 TEST · G3 targeted PASS · Full D7 pending · G4 DENIED</p></footer>
 </main>
}
