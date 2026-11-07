// Interface languages. Add a language by adding a column of translations below.
// Anything not translated falls back to English.
export const LANGS = { en: "English", ar: "العربية", ur: "اردو", es: "Español", fr: "Français" };
const RTL = new Set(["ar", "ur"]);

const D = {
  // header / start
  "BIM Estimator": { ar: "مقدّر BIM", ur: "BIM تخمینہ", es: "Estimador BIM", fr: "Estimateur BIM" },
  "Rates": { ar: "الأسعار", ur: "ریٹس", es: "Precios", fr: "Prix" },
  "Client report": { ar: "تقرير العميل", ur: "کلائنٹ رپورٹ", es: "Informe al cliente", fr: "Rapport client" },
  "Export Excel": { ar: "تصدير Excel", ur: "ایکسل برآمد", es: "Exportar Excel", fr: "Exporter Excel" },
  "Estimate cost straight from your BIM model": { ar: "قدّر التكلفة مباشرة من نموذج BIM", ur: "اپنے BIM ماڈل سے براہ راست لاگت کا تخمینہ", es: "Calcule el coste directamente desde su modelo BIM", fr: "Estimez le coût directement depuis votre maquette BIM" },
  "Upload an IFC file from Revit. Every element is measured from its 3D shape, broken into work items, priced with your rates, and shown on the model.": {
    ar: "ارفع ملف IFC من Revit. يُقاس كل عنصر من شكله ثلاثي الأبعاد ويُقسّم إلى بنود أعمال ويُسعّر بأسعارك ويُعرض على النموذج.",
    ur: "Revit سے IFC فائل اپ لوڈ کریں۔ ہر عنصر کی پیمائش اس کی 3D شکل سے ہوتی ہے، کام کی مدوں میں تقسیم، آپ کے ریٹس سے قیمت، اور ماڈل پر دکھائی جاتی ہے۔",
    es: "Suba un archivo IFC de Revit. Cada elemento se mide desde su forma 3D, se divide en partidas, se valora con sus precios y se muestra en el modelo.",
    fr: "Chargez un fichier IFC de Revit. Chaque élément est mesuré à partir de sa forme 3D, décomposé en ouvrages, chiffré avec vos prix et affiché sur la maquette." },
  "Drop an .ifc file here": { ar: "أفلت ملف ‎.ifc هنا", ur: "‎.ifc فائل یہاں ڈالیں", es: "Suelte un archivo .ifc aquí", fr: "Déposez un fichier .ifc ici" },
  "or click to choose a file": { ar: "أو انقر لاختيار ملف", ur: "یا فائل منتخب کرنے کے لیے کلک کریں", es: "o haga clic para elegir", fr: "ou cliquez pour choisir" },
  "Region": { ar: "المنطقة", ur: "علاقہ", es: "Región", fr: "Région" },
  "Or try a sample": { ar: "أو جرّب مثالاً", ur: "یا نمونہ آزمائیں", es: "O pruebe un ejemplo", fr: "Ou essayez un exemple" },
  "Language": { ar: "اللغة", ur: "زبان", es: "Idioma", fr: "Langue" },
  "Units": { ar: "الوحدات", ur: "اکائیاں", es: "Unidades", fr: "Unités" },
  "Your projects": { ar: "مشاريعك", ur: "آپ کے منصوبے", es: "Sus proyectos", fr: "Vos projets" },
  "How to export IFC from Revit": { ar: "كيفية تصدير IFC من Revit", ur: "Revit سے IFC کیسے برآمد کریں", es: "Cómo exportar IFC desde Revit", fr: "Comment exporter l'IFC depuis Revit" },
  "Add my country / prices": { ar: "أضف بلدي / أسعاري", ur: "اپنا ملک / قیمتیں شامل کریں", es: "Añadir mi país / precios", fr: "Ajouter mon pays / prix" },
  // tabs and steps
  "Summary": { ar: "الملخص", ur: "خلاصہ", es: "Resumen", fr: "Synthèse" },
  "BOQ": { ar: "جدول الكميات", ur: "بی او کیو", es: "Mediciones", fr: "DQE" },
  "Mapping": { ar: "التصنيف", ur: "میپنگ", es: "Asignación", fr: "Affectation" },
  "Checks": { ar: "الفحوصات", ur: "جانچ", es: "Controles", fr: "Contrôles" },
  "Element": { ar: "العنصر", ur: "عنصر", es: "Elemento", fr: "Élément" },
  "Compare": { ar: "مقارنة", ur: "موازنہ", es: "Comparar", fr: "Comparer" },
  "Model": { ar: "النموذج", ur: "ماڈل", es: "Modelo", fr: "Maquette" },
  "Map": { ar: "تصنيف", ur: "میپ", es: "Asignar", fr: "Affecter" },
  "Scope": { ar: "النطاق", ur: "دائرہ", es: "Alcance", fr: "Périmètre" },
  "Check": { ar: "فحص", ur: "جانچ", es: "Revisar", fr: "Vérifier" },
  "Report": { ar: "التقرير", ur: "رپورٹ", es: "Informe", fr: "Rapport" },
  "Cost": { ar: "التكلفة", ur: "لاگت", es: "Coste", fr: "Coût" },
  "Trade": { ar: "الحرفة", ur: "شعبہ", es: "Oficio", fr: "Corps d'état" },
  "Changes": { ar: "التغييرات", ur: "تبدیلیاں", es: "Cambios", fr: "Modifications" },
  "All levels": { ar: "كل الطوابق", ur: "تمام منزلیں", es: "Todas las plantas", fr: "Tous les niveaux" },
  "Fit": { ar: "ملاءمة", ur: "فٹ", es: "Ajustar", fr: "Ajuster" },
  "Show all": { ar: "إظهار الكل", ur: "سب دکھائیں", es: "Mostrar todo", fr: "Tout afficher" },
  // summary
  "Cost build-up": { ar: "تكوين التكلفة", ur: "لاگت کی تفصیل", es: "Desglose del coste", fr: "Décomposition du coût" },
  "Total": { ar: "الإجمالي", ur: "کل", es: "Total", fr: "Total" },
  "Measured work (from the model)": { ar: "الأعمال المقاسة (من النموذج)", ur: "پیمائش شدہ کام (ماڈل سے)", es: "Obra medida (del modelo)", fr: "Travaux métrés (maquette)" },
  "Allowances (work not modelled)": { ar: "مخصصات (أعمال غير منمذجة)", ur: "الاؤنس (غیر ماڈل شدہ کام)", es: "Partidas alzadas (no modelado)", fr: "Provisions (non modélisé)" },
  "Scope check: is the whole building in the model?": { ar: "فحص النطاق: هل المبنى كاملاً في النموذج؟", ur: "دائرہ کار کی جانچ: کیا پوری عمارت ماڈل میں ہے؟", es: "¿Está todo el edificio en el modelo?", fr: "Tout le bâtiment est-il dans la maquette ?" },
  "Commonly forgotten items": { ar: "بنود تُنسى غالباً", ur: "اکثر بھول جانے والی اشیاء", es: "Partidas que se suelen olvidar", fr: "Postes souvent oubliés" },
  "Items measured by hand (not in the model)": { ar: "بنود مقاسة يدوياً (ليست في النموذج)", ur: "ہاتھ سے ناپی گئی اشیاء (ماڈل میں نہیں)", es: "Partidas medidas a mano (fuera del modelo)", fr: "Postes métrés à la main (hors maquette)" },
  "Allowances for work not in the model": { ar: "مخصصات لأعمال خارج النموذج", ur: "ماڈل سے باہر کام کے الاؤنس", es: "Partidas alzadas para obra fuera del modelo", fr: "Provisions pour travaux hors maquette" },
  "Project settings": { ar: "إعدادات المشروع", ur: "منصوبے کی ترتیبات", es: "Ajustes del proyecto", fr: "Paramètres du projet" },
  "Assumptions": { ar: "الافتراضات", ur: "مفروضات", es: "Supuestos", fr: "Hypothèses" },
  "Exclusions": { ar: "الاستثناءات", ur: "اخراجات", es: "Exclusiones", fr: "Exclusions" },
  "By trade": { ar: "حسب الحرفة", ur: "شعبے کے لحاظ سے", es: "Por oficio", fr: "Par corps d'état" },
  "Elemental cost plan": { ar: "خطة التكلفة العنصرية", ur: "عنصری لاگت منصوبہ", es: "Plan de costes por elementos", fr: "Plan de coûts par éléments" },
  "priced": { ar: "مسعّر", ur: "قیمت شدہ", es: "valorado", fr: "chiffré" },
  "missing": { ar: "ناقص", ur: "غائب", es: "falta", fr: "manquant" },
  "allowance": { ar: "مخصص", ur: "الاؤنس", es: "partida alzada", fr: "provision" },
  "Add": { ar: "إضافة", ur: "شامل کریں", es: "Añadir", fr: "Ajouter" },
  // rates dialog
  "Prices & rates": { ar: "الأسعار والمعدلات", ur: "قیمتیں اور ریٹس", es: "Precios y tarifas", fr: "Prix et tarifs" },
  "Save": { ar: "حفظ", ur: "محفوظ کریں", es: "Guardar", fr: "Enregistrer" },
  "Close": { ar: "إغلاق", ur: "بند کریں", es: "Cerrar", fr: "Fermer" },
  "Search": { ar: "بحث", ur: "تلاش", es: "Buscar", fr: "Rechercher" },
  "1 · Local prices": { ar: "١ · الأسعار المحلية", ur: "١ · مقامی قیمتیں", es: "1 · Precios locales", fr: "1 · Prix locaux" },
  "2 · Work item rates": { ar: "٢ · أسعار البنود", ur: "٢ · کام کی مد کے ریٹس", es: "2 · Precios de partidas", fr: "2 · Prix des ouvrages" },
  "3 · Region & sharing": { ar: "٣ · المنطقة والمشاركة", ur: "٣ · علاقہ اور شیئرنگ", es: "3 · Región y compartir", fr: "3 · Région et partage" },
  "Enter what things cost where you work, in {cur}. Every work-item rate is then built up from these prices (labour hours x wage + materials + plant). Start with the <b>key prices</b>; anything you leave empty is estimated from the region's exchange rate and price factors.": {
    ar: "أدخل تكلفة الأشياء حيث تعمل بعملة {cur}. يُبنى كل سعر بند من هذه الأسعار (ساعات العمل × الأجر + المواد + المعدات). ابدأ <b>بالأسعار الرئيسية</b>؛ ما تتركه فارغاً يُقدّر من سعر الصرف ومعاملات المنطقة.",
    ur: "جہاں آپ کام کرتے ہیں وہاں کی قیمتیں {cur} میں درج کریں۔ ہر کام کا ریٹ انہی سے بنتا ہے (مزدوری کے گھنٹے × اجرت + مواد + مشینری)۔ <b>اہم قیمتوں</b> سے شروع کریں؛ خالی چھوڑی گئی قیمتیں شرح تبادلہ اور علاقائی عوامل سے اندازہ کی جاتی ہیں۔",
    es: "Introduzca lo que cuestan las cosas donde trabaja, en {cur}. Cada precio de partida se construye con estos precios (horas × salario + materiales + maquinaria). Empiece por los <b>precios clave</b>; lo que deje vacío se estima con el tipo de cambio y los factores de la región.",
    fr: "Saisissez ce que coûtent les choses là où vous travaillez, en {cur}. Chaque prix d'ouvrage est construit à partir de ces prix (heures × salaire + matériaux + matériel). Commencez par les <b>prix clés</b> ; le reste est estimé avec le taux de change et les facteurs de la région." },
  "prices entered": { ar: "سعر مُدخل", ur: "قیمتیں درج", es: "precios introducidos", fr: "prix saisis" },
  "Resource": { ar: "المورد", ur: "وسیلہ", es: "Recurso", fr: "Ressource" },
  "Unit": { ar: "الوحدة", ur: "اکائی", es: "Unidad", fr: "Unité" },
  "Estimated": { ar: "تقديري", ur: "اندازاً", es: "Estimado", fr: "Estimé" },
  "Your price": { ar: "سعرك", ur: "آپ کی قیمت", es: "Su precio", fr: "Votre prix" },
  "Source / supplier": { ar: "المصدر / المورّد", ur: "ذریعہ / سپلائر", es: "Fuente / proveedor", fr: "Source / fournisseur" },
  "Date": { ar: "التاريخ", ur: "تاریخ", es: "Fecha", fr: "Date" },
  "Key prices (enter these first)": { ar: "الأسعار الرئيسية (أدخلها أولاً)", ur: "اہم قیمتیں (پہلے یہ درج کریں)", es: "Precios clave (introdúzcalos primero)", fr: "Prix clés (à saisir d'abord)" },
  "Labour": { ar: "العمالة", ur: "مزدوری", es: "Mano de obra", fr: "Main-d'œuvre" },
  "Materials": { ar: "المواد", ur: "مواد", es: "Materiales", fr: "Matériaux" },
  "Plant / equipment": { ar: "المعدات", ur: "مشینری", es: "Maquinaria", fr: "Matériel" },
  "e.g. supplier quote": { ar: "مثال: عرض مورّد", ur: "مثلاً سپلائر کا کوٹیشن", es: "p. ej. oferta", fr: "ex. devis" },
  "Each rate is built up from resources. Click a row to see how. Type a fixed rate only if you have a quote for the whole item; it replaces the build-up.": {
    ar: "كل سعر مبني من الموارد. انقر على صف لترى التفاصيل. اكتب سعراً ثابتاً فقط إن كان لديك عرض للبند كاملاً؛ وسيحل محل التحليل.",
    ur: "ہر ریٹ وسائل سے بنتا ہے۔ تفصیل دیکھنے کے لیے قطار پر کلک کریں۔ مقررہ ریٹ صرف تب لکھیں جب پوری مد کا کوٹیشن ہو؛ یہ تجزیے کی جگہ لے گا۔",
    es: "Cada precio se construye con recursos. Haga clic en una fila para verlo. Escriba un precio fijo solo si tiene una oferta de la partida completa; sustituye la descomposición.",
    fr: "Chaque prix est construit à partir de ressources. Cliquez sur une ligne pour le détail. Saisissez un prix fixe seulement si vous avez un devis pour l'ouvrage complet ; il remplace la décomposition." },
  "Work item": { ar: "البند", ur: "کام کی مد", es: "Partida", fr: "Ouvrage" },
  "Built-up rate": { ar: "السعر المبني", ur: "تجزیاتی ریٹ", es: "Precio descompuesto", fr: "Prix décomposé" },
  "Your prices": { ar: "أسعارك", ur: "آپ کی قیمتیں", es: "Sus precios", fr: "Vos prix" },
  "Fixed rate": { ar: "سعر ثابت", ur: "مقررہ ریٹ", es: "Precio fijo", fr: "Prix fixe" },
  "Source": { ar: "المصدر", ur: "ذریعہ", es: "Fuente", fr: "Source" },
  "quote / reference": { ar: "عرض / مرجع", ur: "کوٹیشن / حوالہ", es: "oferta / referencia", fr: "devis / référence" },
  "Qty per": { ar: "الكمية لكل", ur: "مقدار فی", es: "Cant. por", fr: "Qté par" },
  "Price": { ar: "السعر", ur: "قیمت", es: "Precio", fr: "Prix" },
  "your price": { ar: "سعرك", ur: "آپ کی قیمت", es: "su precio", fr: "votre prix" },
  "estimated": { ar: "تقديري", ur: "اندازاً", es: "estimado", fr: "estimé" },
  "No build-up; converted base rate.": { ar: "لا يوجد تحليل؛ سعر أساسي محوّل.", ur: "کوئی تجزیہ نہیں؛ تبدیل شدہ بنیادی ریٹ۔", es: "Sin descomposición; precio base convertido.", fr: "Pas de décomposition ; prix de base converti." },
  "Set up any country. The tool is free: share your prices with colleagues as a rate pack file.": {
    ar: "اضبط أي بلد. الأداة مجانية: شارك أسعارك مع زملائك كملف حزمة أسعار.",
    ur: "کسی بھی ملک کو سیٹ کریں۔ یہ ٹول مفت ہے: اپنی قیمتیں ساتھیوں کے ساتھ ریٹ پیک فائل کے طور پر شیئر کریں۔",
    es: "Configure cualquier país. La herramienta es gratuita: comparta sus precios con colegas como un paquete de precios.",
    fr: "Configurez n'importe quel pays. L'outil est gratuit : partagez vos prix avec vos collègues sous forme de pack de prix." },
  "This region": { ar: "هذه المنطقة", ur: "یہ علاقہ", es: "Esta región", fr: "Cette région" },
  "Name": { ar: "الاسم", ur: "نام", es: "Nombre", fr: "Nom" },
  "Currency": { ar: "العملة", ur: "کرنسی", es: "Moneda", fr: "Devise" },
  "Exchange rate (currency per 1 USD)": { ar: "سعر الصرف (عملة لكل دولار)", ur: "شرح تبادلہ (فی 1 امریکی ڈالر)", es: "Tipo de cambio (por 1 USD)", fr: "Taux de change (pour 1 USD)" },
  "Labour factor (US = 1)": { ar: "معامل العمالة (أمريكا = 1)", ur: "مزدوری عامل (امریکہ = 1)", es: "Factor mano de obra (EE. UU. = 1)", fr: "Facteur main-d'œuvre (US = 1)" },
  "Material factor (US = 1)": { ar: "معامل المواد (أمريكا = 1)", ur: "مواد عامل (امریکہ = 1)", es: "Factor materiales (EE. UU. = 1)", fr: "Facteur matériaux (US = 1)" },
  "Measurement standard": { ar: "معيار القياس", ur: "پیمائش کا معیار", es: "Norma de medición", fr: "Norme de métré" },
  "Preliminaries %": { ar: "التمهيديات %", ur: "ابتدائی اخراجات %", es: "Gastos generales de obra %", fr: "Installations de chantier %" },
  "Save region": { ar: "حفظ المنطقة", ur: "علاقہ محفوظ کریں", es: "Guardar región", fr: "Enregistrer la région" },
  "Update from World Bank": { ar: "تحديث من البنك الدولي", ur: "ورلڈ بینک سے اپ ڈیٹ", es: "Actualizar desde el Banco Mundial", fr: "Mettre à jour (Banque mondiale)" },
  "Share": { ar: "مشاركة", ur: "شیئر", es: "Compartir", fr: "Partager" },
  "Download rate pack": { ar: "تنزيل حزمة الأسعار", ur: "ریٹ پیک ڈاؤن لوڈ", es: "Descargar paquete de precios", fr: "Télécharger le pack de prix" },
  "Import rate pack": { ar: "استيراد حزمة أسعار", ur: "ریٹ پیک درآمد", es: "Importar paquete de precios", fr: "Importer un pack de prix" },
  "Rates to Excel": { ar: "الأسعار إلى Excel", ur: "ریٹس ایکسل میں", es: "Precios a Excel", fr: "Prix vers Excel" },
  "Rates from Excel / CSV": { ar: "الأسعار من Excel / CSV", ur: "ریٹس ایکسل / CSV سے", es: "Precios desde Excel / CSV", fr: "Prix depuis Excel / CSV" },
  "Add your country": { ar: "أضف بلدك", ur: "اپنا ملک شامل کریں", es: "Añada su país", fr: "Ajoutez votre pays" },
  "Country": { ar: "البلد", ur: "ملک", es: "País", fr: "Pays" },
  "Choose…": { ar: "اختر…", ur: "منتخب کریں…", es: "Elija…", fr: "Choisir…" },
  "Region code (optional, e.g. NG_LAGOS for a city)": { ar: "رمز المنطقة (اختياري، مثل SA_RIYADH لمدينة)", ur: "علاقے کا کوڈ (اختیاری، مثلاً PK_LAHORE شہر کے لیے)", es: "Código de región (opcional, p. ej. MX_CDMX)", fr: "Code région (facultatif, ex. FR_PARIS)" },
  "Create region": { ar: "إنشاء منطقة", ur: "علاقہ بنائیں", es: "Crear región", fr: "Créer la région" },
  "After creating it: click Update from World Bank (needs internet) or type the exchange rate, then enter local prices in tab 1.": {
    ar: "بعد الإنشاء: انقر تحديث من البنك الدولي (يتطلب الإنترنت) أو اكتب سعر الصرف، ثم أدخل الأسعار المحلية في التبويب ١.",
    ur: "بنانے کے بعد: ورلڈ بینک سے اپ ڈیٹ پر کلک کریں (انٹرنیٹ درکار) یا شرح تبادلہ لکھیں، پھر ٹیب ١ میں مقامی قیمتیں درج کریں۔",
    es: "Después: pulse Actualizar desde el Banco Mundial (requiere internet) o escriba el tipo de cambio, y luego introduzca precios locales en la pestaña 1.",
    fr: "Ensuite : cliquez sur Mettre à jour (Banque mondiale, internet requis) ou saisissez le taux de change, puis les prix locaux dans l'onglet 1." },
  "Region saved.": { ar: "تم حفظ المنطقة.", ur: "علاقہ محفوظ ہو گیا۔", es: "Región guardada.", fr: "Région enregistrée." },
  "Region created.": { ar: "تم إنشاء المنطقة.", ur: "علاقہ بن گیا۔", es: "Región creada.", fr: "Région créée." },
  "Saved": { ar: "تم حفظ", ur: "محفوظ", es: "Guardado", fr: "Enregistré" },
  "prices": { ar: "أسعار", ur: "قیمتیں", es: "precios", fr: "prix" },
  "fixed rates": { ar: "أسعار ثابتة", ur: "مقررہ ریٹس", es: "precios fijos", fr: "prix fixes" },
  "Imported": { ar: "تم الاستيراد", ur: "درآمد شدہ", es: "Importado", fr: "Importé" },
  "Updating the estimate…": { ar: "جارٍ تحديث التقدير…", ur: "تخمینہ اپ ڈیٹ ہو رہا ہے…", es: "Actualizando la estimación…", fr: "Mise à jour de l'estimation…" },
  "Estimate updated.": { ar: "تم تحديث التقدير.", ur: "تخمینہ اپ ڈیٹ ہو گیا۔", es: "Estimación actualizada.", fr: "Estimation mise à jour." },
};

let lang = "en";
try { lang = localStorage.getItem("bim5d.lang") || (navigator.language || "en").slice(0, 2); } catch { /* ignore */ }
if (!LANGS[lang]) lang = "en";

export function t(key, vars) {
  let s = (lang !== "en" && D[key] && D[key][lang]) || key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}
export const getLang = () => lang;
export function setLang(l) {
  lang = LANGS[l] ? l : "en";
  try { localStorage.setItem("bim5d.lang", lang); } catch { /* ignore */ }
  applyStatic();
}
export function applyStatic(root = document) {
  document.documentElement.lang = lang;
  document.documentElement.dir = RTL.has(lang) ? "rtl" : "ltr";
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    if (!el.dataset.i18nKey) el.dataset.i18nKey = el.dataset.i18n;
    el.innerHTML = t(el.dataset.i18nKey);
  });
  root.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
}
