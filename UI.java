/**
 * 
 */
package com.accurev.git_server;


import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;

import org.openqa.selenium.By;

import com.accurev.browser.Browser;
import com.accurev.common.AccuRev;
import com.accurev.common.Logging;
import com.accurev.gitserver.AccuRevGitServer;
import com.accurev.gitserver.pages.AccessControlList;
import com.accurev.gitserver.pages.AdminErrorMessage;
import com.accurev.gitserver.pages.AllRepos;
import com.accurev.gitserver.pages.Configuration;
import com.accurev.gitserver.pages.CreateGitRepo;
import com.accurev.gitserver.pages.Login;
import com.accurev.gitserver.pages.MyClonedRepos;
import com.accurev.gitserver.pages.Navigation;
import com.accurev.gitserver.widgets.PopupMultiSelectTypeahead;
import com.accurev.utils.CLITest;
import com.accurev.utils.Confirm;
import com.accurev.utils.ScriptSupport;

import cucumber.api.java.After;
import cucumber.api.java.Before;
import cucumber.api.java.en.And;
import cucumber.api.java.en.Given;
import cucumber.api.java.en.Then;
import cucumber.api.java.en.When;


/**
 * Login UI
 * @author LNodwell
 *
 */
public class ImplGitServerLogin {
	private static final String NOT_FOUND = "*** PROPERTY NOT FOUND ***";
	protected String CLICONFIG = "BURL-LNODWELL.cfg";

	protected Properties propertiesCLI;
	protected Properties properties;
	public String pathConfig = null;

	private String clipboardContents = null;
	Login gitserverLogin = new Login();

	AccuRev accurev = AccuRev.getInstance();
	AccuRevGitServer proxy = new AccuRevGitServer();

	@Before("@None")
	public void noneBefore() {
		Logging.step("@None Before");
	}



	@Before("@NewSetup")
	public void newSetupBefore() throws InterruptedException {
		Logging.step("@ewSetup Before");

		Path config_new =Paths.get("D:/AccuRev_Dev/git-server/conf/empty_config.properties");
		File config = new File("D:/AccuRev_Dev/git-server/conf/config.properties");

		//System.out.println("config.exists= " + config.exists());
		try {
			//System.out.println("config.deleted= " + config.delete());
			Thread.sleep(250);
			//System.out.println("config.exist after delete= " + config.exists());
			Files.copy(config_new, config.toPath(), StandardCopyOption.REPLACE_EXISTING);
			Thread.sleep(250);
			//System.out.println("config.exists after copy= " + config.exists());
		} catch (IOException e) {
			e.printStackTrace();
		}



	}

	@After("@None")
	public void noneAfter() {
		Logging.step("@None After");
		try {

			new Browser().browserLog();
		} catch (Exception e) {
			Logging.warn("Exception while outputting browser log: " + e.getMessage());
			e.printStackTrace();
		}
		try {
			Browser.quit();
		} catch (Exception e) {
			Logging.warn("Exception while quitting browser: " + e.getMessage());
			e.printStackTrace();
		}
	}

	@Before("@GitURL")
	public void beforeGitLoginPage() {
		Logging.step("@GitURL Before");
		//beforeInitialGitServerDepot
		proxyLaunchURL();
		proxyLoginDialogIsDisplayed();

	}

	//@Before("@InitialGitServerDepot")
	@Before()
	public void beforeInitialGitServerDepot() {
		Logging.step("Before");
		Logging.info("Loading configs");
		pathConfig = "gui_ac/git-server/initial-git-server-depot.cfg";


		Confirm.isTrue("Config file [" + pathConfig + "] is loaded", loadConfig(), true);
		Confirm.isTrue("CLI config file [" + CLICONFIG +"] is loaded", loadCLIConfig(), true);

	}

	@After("@GitURL")
	public void afterGitURL() {
		Logging.step("@GitURL After");

	}

	@Given ("^Git Server is configured on localhost$")
	public void enableProxy() {
		Logging.step("AccuRev Web GUI is enabled");
		Confirm.isTrue("Verify AccuRev services are running", accurev.verifyAccuRevSvcExists(), true);

	}

	@And("^Git Server URL is entered$")
	public void proxyLaunchURL() {
		Logging.step("Go to Proxy URL");
		// start browser
		//enter url:   http://<webui-host>:8080/git-server

		Confirm.isTrue("Proxy UI is launched successfully", proxy.start(), true);
	}


	@And("^Git Server Login is displayed$")
	public void proxyLoginDialogIsDisplayed() {
		Logging.step("Verify Proxy Login dialog is displayed");

		Confirm.isTrue("Proxy Login dialog is displayed", gitserverLogin.exists(ScriptSupport.LONG_TIME_OUT), true);
		Confirm.isTrue("Proxy Login title is displayed", gitserverLogin.getTitle().exists(), true);	
		Confirm.contains("Proxy Login title contains " + Login.PROXY_LOGIN_TITLE_ACCUREV, Login.PROXY_LOGIN_TITLE_ACCUREV, gitserverLogin.getTitle().getText(), true);	
		Confirm.matches("Proxy Login title contains " + Login.PROXY_LOGIN_TITLE, Login.PROXY_LOGIN_TITLE, gitserverLogin.getTitle().getText().replaceAll("(\\r|\\n)", ""), true);
	}

	@When("^Valid Git Server User Name and Password are entered$")
	public void proxyEnterNamePasswordLogin() {
		Logging.info("Entering default user name and password");
		proxyEnterNamePasswordLogin("ACCUREV_ADMIN_USERNAME", "ACCUREV_ADMIN_PASSWORD");
	}	

	//@When("Valid Git Server User Name {string} and Password {string} are entered")
	@When("Valid Git Server User Name \"([^\"]*)\" and Password \"([^\"]*)\" are entered")
	public void proxyEnterNamePasswordLogin(String username, String password) {
		Logging.step("Enter user name ["  + username + "] and password [" + password + "]");
		boolean bSuccess = true;

		username = properties.getProperty(username, NOT_FOUND);
		password = properties.getProperty(password, NOT_FOUND);

		bSuccess &= Confirm.isFalse("Login button is not enabled", gitserverLogin.getLogin().isEnabled());

		bSuccess &= Confirm.isTrue("User Name field is displayed", gitserverLogin.getUserNameField().exists());

		gitserverLogin.getUserNameField().setText(username);
		System.out.println("&&&&&&&&&&&&& &&&&&&&&&&&& User Name field contents: " + gitserverLogin.getUserNameField().getText());


		//try {Thread.sleep(1000);} catch (InterruptedException e) {;};
		bSuccess &= Confirm.isTrue("Login button is now enabled", gitserverLogin.getLogin().isEnabled(ScriptSupport.LONG_TIME_OUT));

		bSuccess &= Confirm.isTrue("Password field is displayed", gitserverLogin.getPasswordField().exists());

		gitserverLogin.getPasswordField().setText(password);
		System.out.println("&&&&&&&&&&&&& &&&&&&&&&&&& Password field contents: " + gitserverLogin.getPasswordField().getText());

		bSuccess &= gitserverLogin.getLogin().isEnabled(ScriptSupport.LONG_TIME_OUT);
		bSuccess &= gitserverLogin.getLogin().click();

		Confirm.isTrue("Proxy Login user name and password can be entered successfully", bSuccess, true);	
	}

	// TODO : combine with goToShowAllReposFromMyClonedRepos
	@Then("^Go to Show All Repos from Configuration$")
	public void goToShowAllReposFromConfiguration() {
		Logging.step("Go to Show All Repos from Configuration");
		Configuration configurationPage = new Configuration();
		Confirm.isTrue("Show All Repos is displayed", configurationPage.getShowAllRepos().exists(ScriptSupport.LONG_TIME_OUT), true);
		configurationPage.getShowAllRepos().click();
		Confirm.isTrue("All Repos page is displayed",  new AllRepos().exists(ScriptSupport.LONG_TIME_OUT), true);
	}


	@Then("^Go to Show All Repos from My Cloned Repos$")
	public void goToShowAllReposFromMyClonedRepos() {
		Logging.step("Go to Show All Repos from My Cloned Repos");
		MyClonedRepos myClonedRepos = new MyClonedRepos();


		Confirm.isTrue("Home Page [My Cloned Repos] is displayed", new MyClonedRepos().exists(ScriptSupport.LONG_TIME_OUT));


		Confirm.isTrue("Show All Repos is displayed", myClonedRepos.getShowAllRepos().exists(ScriptSupport.LONG_TIME_OUT), true);
		Confirm.isTrue("Show All Repos is visible", myClonedRepos.getShowAllRepos().isDisplayed(), true);

		myClonedRepos.getShowAllRepos().click();


		Confirm.isTrue("All Repos page is displayed",  new AllRepos().exists(ScriptSupport.LONG_TIME_OUT), true);
	}


	/**
	 * The option to create git repos is available for admins only
	 */
	@Then("^Go to Create Git Repo$")
	public void goToCreateRepo() {
		Logging.step("Go to Create Git Repo from All Repos");

		AllRepos allRepos = new AllRepos();
		CreateGitRepo createGitRepo = new CreateGitRepo();
		Confirm.isTrue("All Repos page is displayed", allRepos.exists(ScriptSupport.LONG_TIME_OUT));
		Confirm.isTrue("Create Git Repo button is displayed", allRepos.getCreateGitRepo().exists(ScriptSupport.LONG_TIME_OUT), true);
		Confirm.isTrue("Create Git Repo button is enabled", allRepos.getCreateGitRepo().isEnabled(ScriptSupport.LONG_TIME_OUT), true);
		allRepos.getCreateGitRepo().click();


		Confirm.isTrue("Create Git Repo page is displayed", createGitRepo.exists(ScriptSupport.LONG_TIME_OUT), true);


		System.out.println("****************** checking out items on the page to get good locators");
		System.out.println("****************** number of 'rows': " + createGitRepo.getPage().getControl().findElements(By.cssSelector("div.row")).size());



	}

	@Then("^the current user logs out$")
	public void logoutCurrentUser() {
		Logging.step("Current user logs out from git-server");

		Confirm.isTrue("Current user is logged out then login page is displayed", new Navigation().logoutCurrentUser(), true);
	}

	@Then("^Admin option is displayed$")
	public void navigateToAdmininistrationIsDisplayed()
	{
		Confirm.isTrue("Administrator navigation is displayed", new Navigation().administrationNavButton().exists(ScriptSupport.LONG_TIME_OUT), true);
	}
	/**
	 * Clones the specified repo and checks acl group and enters specified description
	 * The aclGroupRoot is the root name of the acl group.  For example, ACL_GROUP1 is
	 * the root name of acl group ACL_GROUP1_NAME and member list ACL_GROUP1_MEMBERS and
	 * corresponding stream ACLGROUP1_STREAM
	 */
	@When("^Create a Git Repo from Depot \"([^\"]*)\" Stream \"([^\"]*)\" ACL Group Root \"([^\"]*)\" and Description \"([^\"]*)\"$")
	public void createGitRepo(String depotName, String streamName, String aclGroupRoot, String description) {
		boolean bSuccess = true;
		Logging.step("Create a Git Repo from AccuRev Stream");

		// using a default so that if there is an error is it easy to identify that there was an error getting the property
		String depot = properties.getProperty(depotName, NOT_FOUND);
		String stream = properties.getProperty(streamName, NOT_FOUND);
		String aclMembers = properties.getProperty(aclGroupRoot + "_MEMBERS", NOT_FOUND);
		String aclGroup = properties.getProperty(aclGroupRoot + "_NAME", NOT_FOUND);


		CreateGitRepo createGitRepo = new CreateGitRepo();
		bSuccess &= Confirm.isTrue("Create a Git Repo page is displayed", createGitRepo.exists(ScriptSupport.LONG_TIME_OUT), true);
		bSuccess &= Confirm.isTrue("Depot Name field is displayed", createGitRepo.getDepotNameField().exists(ScriptSupport.LONG_TIME_OUT), true);


		//System.out.println("stream names " + createGitRepo.getDepotNameField().getPopupListItems().toString());
		bSuccess &= Confirm.isTrue("Depot [" + depot + "] is selected", createGitRepo.getDepotNameField().select(depot));




		bSuccess &= Confirm.isTrue("Stream Name field is displayed after valid depot is selected", createGitRepo.getStreamNameField().exists(ScriptSupport.LONG_TIME_OUT));
		bSuccess &= Confirm.isTrue("Stream [" + stream + "] is selected from stream list", createGitRepo.getStreamNameField().select(stream));


		bSuccess &= Confirm.isTrue("Create Repo button is displayed after valid stream is selected", createGitRepo.getCreateRepo().exists(ScriptSupport.LONG_TIME_OUT));
		bSuccess &= Confirm.isTrue("Create Repo button is enabled after valid stream is selected", createGitRepo.getCreateRepo().isEnabled(ScriptSupport.LONG_TIME_OUT));
		bSuccess &= Confirm.isTrue("Repo Description field is displayed after valid stream is selected", createGitRepo.getDescriptionField().exists(ScriptSupport.LONG_TIME_OUT));

		if (description == null || description.isEmpty()) {
			Logging.info("No description entered for this depot/stream");
		} else {

			System.out.println("^^^ &&& ^^^ set text to " + createGitRepo.getDescriptionField().setText(description));
		}


		bSuccess &= Confirm.isTrue("Create Repo is clicked successfully", (createGitRepo.getCreateRepo().exists() && createGitRepo.getCreateRepo().isEnabled() && createGitRepo.getCreateRepo().click()), true);

		bSuccess &= Confirm.isTrue("ACL page is displayed", new AccessControlList().exists(ScriptSupport.LONG_TIME_OUT), true);
		List<String> actualACL = new AccessControlList().getACLItems();

		if (aclGroupRoot == null || aclGroupRoot.isEmpty()) {
			Logging.info("No ACL group - no validation of ACL contents");
			Logging.info("ACL : " + actualACL.toString());
		} else {
			// validate acl here
			// aclMembers is space-separated list
			List<String> expectedMembers = Arrays.asList(aclMembers.split(" "));

			List<String> expectedMembersAndGroups = new ArrayList<String>();
			expectedMembersAndGroups.addAll(expectedMembers);
			expectedMembersAndGroups.add(aclGroup);

			// also add the group name as it is part of the acl
			boolean bAllFound = true;
			for (String s : expectedMembersAndGroups) {
				bAllFound &= Confirm.isTrue("Actual ACL list contains [" + s +"]", actualACL.contains(s));
			}
			bSuccess &= Confirm.isTrue("Actual ACL list contains all expected members and groups",  bAllFound);
		}


		bSuccess &= Confirm.isTrue("Verify back button exists", new AccessControlList().getBackButton().exists(ScriptSupport.LONG_TIME_OUT), true);
		new AccessControlList().getBackButton().click();
		bSuccess &= Confirm.isTrue("Verify back button returns user to All Repos page from ACL page", new AllRepos().exists(ScriptSupport.LONG_TIME_OUT));	

		Confirm.isTrue("Repo [" + stream + "] created successfully with expected ACL members", bSuccess, true);
	}


	@Then("^Stream \"([^\"]*)\" Repo is displayed on All Repos page with Description \"([^\"]*)\"$")
	public void verifyAllReposStreamDescription(String streamName, String description) {
		Logging.step("Repo is displayed on All Repos page and description is as expected");
		streamName = properties.getProperty(streamName, NOT_FOUND);

		boolean bSuccess = true;
		bSuccess &= Confirm.isTrue("Verify All Repos page is displayed", new AllRepos().exists(ScriptSupport.LONG_TIME_OUT), true);

		AllRepos allReposPage = new AllRepos();
		System.out.println("repos listed are " + allReposPage.getAllRepos().toString());


		List<String> allRepos = allReposPage.getAllRepos();
		allRepos.contains(streamName);


		bSuccess &= Confirm.isTrue("List of repos contains repo [" + streamName + "]", allRepos.contains(streamName));
		// output the available repo names if we fail to find the specified repo name
		if (!bSuccess) {
			Logging.warn("Available repos from All Repos page: " + allRepos.toString());
		}

		bSuccess &= Confirm.equals("Description for repo [" + streamName + "] matches expected", description, allReposPage.getRepoDescription(streamName));

	}


	@Then("^Git Server Home Page is displayed$")
	public void proxyHomePageDisplayed() {
		Logging.step("Git Server Home Page is displayed");
		Confirm.isTrue("Home Page [My Cloned Repos] is displayed", new MyClonedRepos().exists(ScriptSupport.LONG_TIME_OUT), true);
	}

	// CHECK INITIAL VALUES HERE
	@Then("^Git Server Configuration Page is displayed$")
	public void proxyConfigPageDisplayed() {
		Logging.step("Git Server Configuration Page is displayed");
		Confirm.isTrue("Configuration Page is displayed", new Configuration().exists(ScriptSupport.LONG_TIME_OUT), true);
	}


	@And("^Navigate to Configuration Page$")
	public void goToConfig() throws InterruptedException {



		Navigation nav = new Navigation();
		//nav.getMenuBar().exists(5000);


		Confirm.isTrue("Administration option exists", nav.administrationNavButton().exists(ScriptSupport.LONG_TIME_OUT), true);
		nav.administrationNavButton().click();
		Confirm.isTrue("Configuration page is displayed after clicking Administration", new Configuration().exists(ScriptSupport.LONG_TIME_OUT), true);

	}


	@When("^Valid Configuration Data is Entered$")
	public void validConfigDataEntered() {
		Logging.step("Enter valid configuration data");
		Configuration configurationPage = new Configuration();
		Confirm.isTrue("Configuration Page is displayed", configurationPage.exists(), true);


		// try to get the help text below bridge user field
		System.out.println("******************** has help message: " + configurationPage.getBridgeUser().hasHelpMessage());
		System.out.println("******************** help message: " + configurationPage.getBridgeUser().getHelpMessage());
		System.out.println("******************** has help message: " + configurationPage.getBridgePassword().hasHelpMessage());
		System.out.println("******************** help message: " + configurationPage.getBridgePassword().getHelpMessage());


		String bridgeUserName = properties.getProperty("BRIDGE_USERNAME", NOT_FOUND);
		String bridgePassword = properties.getProperty("BRIDGE_PASSWORD", NOT_FOUND);

		configurationPage.getBridgeUser().setText(bridgeUserName);
		configurationPage.getBridgePassword().setText(bridgePassword);
	}
	@Then("^Configuration is Saved Successfully$") 
	public void proxyConfigSavedOK() throws Exception {
		Logging.step("Verify valid config data is saved");
		Configuration configurationPage = new Configuration();
		Confirm.isTrue("Configuration Page is displayed", configurationPage.exists(), true);
		Confirm.isTrue("Save button exists", configurationPage.getSave().exists(ScriptSupport.LONG_TIME_OUT));
		Confirm.isTrue("Save button is enabled", configurationPage.getSave().isEnabled(ScriptSupport.LONG_TIME_OUT), true);
		configurationPage.getSave().click();
		Confirm.isFalse("Save button is no longer enabled", configurationPage.getSave().isEnabled(), true);


	}



	@Then("^current user saves an admin group$")
	public void setAdminGroup() throws Exception {

		Logging.step("Verify admin group can be selected and saved");
		String adminGroupName = properties.getProperty("ADMIN_GROUP_NAME", NOT_FOUND);

		Configuration configurationPage = new Configuration();
		Confirm.isTrue("Configuration Page is displayed", configurationPage.exists(ScriptSupport.LONG_TIME_OUT), true);

		// this delay fixes the problem with selecting the admin group and not having the save button get enabled.
		// need to find a better way to handle this.
		//Thread.sleep(10000);

		PopupMultiSelectTypeahead adminGroup = configurationPage.getAdminGroup();

		Confirm.isTrue("Configuration Admin Group is displayed", adminGroup.exists(ScriptSupport.LONG_TIME_OUT), true);
		Confirm.isTrue("Admin group name [" + adminGroupName + "] can be selected", adminGroup.select(adminGroupName), true);

		List<String> adminGroups = adminGroup.getSelectedItems();
		Confirm.isTrue("Admin group [" + adminGroupName + "] found in selected groups", adminGroups.contains(adminGroupName));

		Confirm.isTrue("Save button exists", configurationPage.getSave().exists(ScriptSupport.LONG_TIME_OUT));
		Confirm.isTrue("Save button is enabled", configurationPage.getSave().isEnabled(ScriptSupport.LONG_TIME_OUT), true);
		configurationPage.getSave().click();
		Confirm.isFalse("Save button is no longer enabled", configurationPage.getSave().isEnabled(), true);


	}

	/**
	 * Work with Al Repos page to get the URL to clone a repo
	 * @param streamName
	 */
	@Then("^Repo \"([^\"]*)\" URL Can Be Accessed$")
	public void copyURL(String streamName) {
		boolean bSuccess = true;
		streamName = properties.getProperty(streamName, NOT_FOUND);
		Logging.step("Repo URL for [" + streamName + "] can be accessed");
		AllRepos allReposPage = new AllRepos();
		bSuccess &= Confirm.isTrue("All Repos page is displayed",  allReposPage.exists(ScriptSupport.LONG_TIME_OUT), true);
		bSuccess &= Confirm.isTrue("Repo [" + streamName + "] is found in All Repos", allReposPage.hasRepo(streamName), true);

		//String url = allReposPage.getURL(streamName);
		//System.out.println("url is : " + url);

		// clear the clipboard before attempting to copy the url
		ScriptSupport.clearClipboard();

		// copy the url then get the clipboard contents
		allReposPage.copyURL(streamName);
		String result = ScriptSupport.getClipboardContents();
		bSuccess &= Confirm.isNotNull("Clipboard has contents", result);
		bSuccess &= Confirm.contains("Clipboard contains stream name", streamName, result);

		// if this test fails then set the internal clipboard contents to null to indicate that
		clipboardContents = (bSuccess) ? result : null;

		Confirm.isTrue("Stream is found in All Repos page and URL is copied to clipboard", bSuccess, true);

	}


	@Then("^Clone a Repo as user \"([^\"]*)\" password \"([^\"]*)\"$")
	public void cloneRepoFromClipboard(String username, String password) {
		// set up the cli test by creating a config file with the specified data
		username = properties.getProperty(username, NOT_FOUND);
		password = properties.getProperty(password, NOT_FOUND);
		Logging.step("Clone a repo as user " + username + " with passowrd " + password);
		boolean bSuccess = true;

		AllRepos allReposPage = new AllRepos();
		bSuccess &= Confirm.isTrue("All Repos page is displayed",  allReposPage.exists(ScriptSupport.LONG_TIME_OUT), true);

		//  get the contents of the clipboard
		bSuccess &= Confirm.isNotNull("Clipboard storage contains data", clipboardContents, true);
		String cloneURL = clipboardContents;
		String[] temp = cloneURL.split("/");
		// get the last item then remove the .git to get the repo name
		String repoName = temp[temp.length - 1].replace(".git", "");

		// remove the http:// because we need to prepend user name and password to the url
		cloneURL = cloneURL.replace( "http://", "");


		String pathCloneRepoConfig = "gui_ac/git-server/clonerepo.cfg";
		String pathCloneRepoXML = "gui_ac/git-server/clonerepo";
		File fileCloneRepoConfig = new File(ScriptSupport.getCLIProjectPath(), pathCloneRepoConfig);

		// properties file writer escapes the : and we can't run the CLI with that char in the file
		try (PrintWriter printWriter = new PrintWriter( fileCloneRepoConfig )) {
			printWriter.println( "#" + LocalDateTime.now());
			printWriter.println( "USERNAME=" + username);
			printWriter.println( "PASSWORD=" + password);
			printWriter.println( "CLONE_URL=" + cloneURL);
		} catch (FileNotFoundException e) {
			Logging.warn("Exception writing file " + fileCloneRepoConfig + " : " + e.getMessage());
			bSuccess &= false;
		} catch (Exception e) {
			Logging.warn("Unhandled exception writing file " + fileCloneRepoConfig + " : " + e.getMessage());
			bSuccess &= false;
		}
		bSuccess &= Confirm.isTrue("Settings for CLI are written to config file " + fileCloneRepoConfig.getPath(), bSuccess, true);

		// now run the cli with -k option to not reset the environment
		bSuccess &= Confirm.isTrue("CLI run is successful", CLITest.getInstance().runCLITest(pathCloneRepoXML, true));


		// check for existence of the directory in scratch area / clone
		File repoFolder = new File(propertiesCLI.getProperty("SCRATCH_AREA", NOT_FOUND), "clone");
		bSuccess &= Confirm.isTrue("git clone directory exists[" + repoFolder.toString() + "]", repoFolder.exists());
		bSuccess &= Confirm.isTrue("Repo [" + repoName +"] found after cloning", new File(repoFolder, repoName).exists());


		allReposPage.goBack().click();

		MyClonedRepos homePage = new MyClonedRepos();
		bSuccess &= Confirm.isTrue("My Cloned Repos page is displayed", homePage.exists(ScriptSupport.LONG_TIME_OUT), true);
		bSuccess &= Confirm.isTrue("My Cloned Repos page contains repo [" + repoName +"]", homePage.hasRepo(repoName), true);
		Confirm.isTrue("User has performed clone stream successfully", bSuccess, true);

	}




	@Then("^Not Configured Message is Displayed$")
	public void notConfiguredMessageDisplayed() {
		Logging.step("Not configured message is displayed");
		boolean bSuccess = true;
		AdminErrorMessage adminErrorMessagePage =  new AdminErrorMessage();
		Confirm.isTrue("Admin error message is displayed", adminErrorMessagePage.exists(ScriptSupport.LONG_TIME_OUT), true);
		String msg = adminErrorMessagePage.getMessage();
		bSuccess &= Confirm.contains("Error message contains not configured phrase", AdminErrorMessage.NOT_CONFIGURED, msg);
		bSuccess &= Confirm.contains("Error message contains ask admin to configure phrase", AdminErrorMessage.ASK_ADMIN, msg);
		Confirm.isTrue("Error message contains all expected phrases", bSuccess, true);
	}


	@When("^the user logs out$")
	public void userLogOut() {
		Logging.step("Current user can logout");
	}

	/**
	 * Loads the properties from the test config file
	 * @return true if test config file is found and loaded; false otherwise
	 */
	private boolean loadConfig() {
		Logging.step("Loading test config file");
		boolean bSuccess= false;


		File config = new File(ScriptSupport.getCLIProjectPath(), pathConfig);
		properties = new Properties();
		bSuccess = Confirm.isTrue("Config file exists at " + config.getAbsolutePath(), config.exists(), true);

		try (InputStream inputStream = new FileInputStream(config.getPath())) {


			// load a properties file
			properties.load(inputStream);

			// read a value
			bSuccess = properties.containsKey("DEPOT");
		} catch (FileNotFoundException e) {
			Logging.error("File not found; cannot be read");
		} catch (NullPointerException e) {
			Logging.error("Config file cannot be null");
		} catch (IOException e) {
			Logging.error("Config file IOException " + e.getMessage());
		}
		return bSuccess;
	}

	/**
	 * Loads the properties from the system config file
	 * TODO load file from hostname and/or specific gui auto config file name
	 * @return true if config file is found and loaded; false otherwise
	 */
	private boolean loadCLIConfig() {
		Logging.step("Loading system config file");
		boolean bSuccess= false;
		File config = new File(ScriptSupport.getCLIProjectPath(), CLICONFIG);
		propertiesCLI = new Properties();
		bSuccess = Confirm.isTrue("Config file exists at " + config.getAbsolutePath(), config.exists(), true);

		FileReader fileReader;
		try {
			fileReader = new FileReader(config);

			try (BufferedReader input = new BufferedReader(fileReader)) {

				String line = null;

				while ((line = input.readLine()) != null) {
					String[] property;
					System.out.println(line);
					if (line.trim().startsWith("#")) {
						; // skip this line it's a comment
					} else {
						property = line.split("=");
						if (property.length == 2) {
							propertiesCLI.setProperty(property[0].trim(), property[1].trim());
						} else {
							; //skip
						}
					}
				}
			}

		} catch (FileNotFoundException e) {
			Logging.warn("Unable to read property file : " + e.getMessage());
			bSuccess = false;

		} catch (IOException e) {
			Logging.warn("Unable to read property file : " + e.getMessage());
			bSuccess = false;
		}


		//		try (InputStream inputStream = new FileInputStream(config.getPath())) {
		//
		//
		//			// load the properties file
		//			propertiesCLI.load(inputStream);
		//
		//			// read a value
		//			bSuccess = propertiesCLI.containsKey("SERVER_NAME");
		//		} catch (FileNotFoundException e) {
		//			Logging.error("File not found; cannot be read");
		//		} catch (NullPointerException e) {
		//			Logging.error("Config file cannot be null");
		//		} catch (IOException e) {
		//			Logging.error("Config file IOException " + e.getMessage());
		//		}
		return bSuccess;
	}


}
